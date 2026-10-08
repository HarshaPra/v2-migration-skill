# ThinkAR OTA Tool → V2

The OTA tool is the internal firmware updater that staff use on customers' or stock glasses. It is **not** the customer app. It signs in with a shared engineer account, updates one pair of glasses, then releases them and signs out. It exists for Android and iOS; the flow and the V2 contract are the same on both.

Read this file **only** when the codebase is the OTA tool. Where it differs from `SKILL.md`, this file wins. Everything it doesn't mention (error format, camelCase bodies, string ids, no refresh) follows `SKILL.md`.

---

## 1. How to recognise it

The codebase is the OTA tool if most of these hold:

- Its only server calls are sign-in, token refresh, `firmware/latest/{code}`, `firmware/download/{id}` and `firmware/update-log` (create + update). No live agent, translation, profile or device list.
- The operator types a **brand verification code** (`AISIN`, `Appoconn`, `CASALIZ`, `THINKAR`) that maps to a firmware code (`10`, `11`, `13`, `0`).
- It signs in with **one fixed engineer account**, not a user-entered account.
- BLE pairing uses a **hardcoded glasses user id** (Android: `23412`) and a cloud token generated in the app.
- It forces a reflash by sending `currentVersion=0` when the glasses' major version doesn't match the brand code.
- After an update (or "already latest"), it sends the BLE **unbind** command, removes the OS Bluetooth bond, clears local device data and signs out.

Android reference points (package `com.thinkar.ota`): `api/API.kt`, `api/BaseRequest.kt`, `api/Session.kt`, `verification/VerificationFragment.kt` (brand codes, sign-in, version check), `ble/AiLens.kt` (pairing user id and cloud token), `ble/FirmwareManager.kt`, `ble/FirmwareUpdateLogger.kt`, `ble/FirmwareUpdateService.kt` (`performUnbindAndCleanup`). On iOS, find the equivalents by behavior.

---

## 2. Where it differs from `SKILL.md`

| `SKILL.md` | OTA tool |
|---|---|
| Send `x-install-id` on every sign-in (one phone per account) | **Don't send it.** Many station phones share one account. Only sessions that carry an install id sign out older phones (`auth/one-phone.ts`), so leaving it out keeps every phone signed in |
| The user keeps the device after bind | **Release it** at the end of every run: report → server unbind → BLE unbind → remove bond → sign out |
| Pair only after `lookup` says `claimable` / `owned_by_me` | Same, but a non-claimable state ends the run with a message to the operator |
| Firmware model chosen by the server | Same. The brand code becomes an **app-side check only** (glasses' major version must match it); it is never sent to the server |
| 401 → go to sign-in | The tool signs in itself: clear the session and sign in again once. Still no refresh flow |

---

## 3. V1 → V2 mapping

| V1 | V2 | Notes |
|---|---|---|
| `POST /api/v1/auth/signin` | `POST /v2/auth/sign-in/email { email, password }` | Store the body `token` only, as Bearer |
| `GET /api/v1/auth/refresh` | — | Remove. Delete refresh token, `expiresAt` and the pre-request refresh |
| sign-in `user.session.userId` | `GET /v2/auth/get-session` → `user.id` (UUID), `user.glassUserId` (number) | |
| hardcoded BLE user id | `user.glassUserId` | Sign in **before** pairing, so the id is known |
| — (no server call) | `POST /v2/devices/lookup { macAddress }` | New. Before pairing |
| — (no server call) | `POST /v2/devices/bind { macAddress, deviceToken, modelCode, firmwareVersion, name? }` | New. After the BLE handshake. Keep the returned `id` |
| `GET /api/v1/firmware/latest/{code}?currentVersion&deviceType` | `GET /v2/devices/{id}/firmware/check?currentVersion=` | By bound device id. Send the glasses' **real** version |
| `GET /api/v1/firmware/download/{id}` → `download_url` | `release.url` from the check | Valid 15 minutes |
| `POST` + `PATCH /api/v1/firmware/update-log` | `POST /v2/devices/{id}/firmware/updates` | One report at the end |
| BLE unbind only | `POST /v2/devices/{id}/unbind`, then BLE unbind | New server step |
| local logout | `POST /v2/auth/sign-out`, then clear local state | |

Base URL: one `https://<host>/v2` constant per environment.

---

## 4. Run flow

```
1. Sign in            POST /v2/auth/sign-in/email          → token
2. Session            GET  /v2/auth/get-session            → user.glassUserId
3. Clean-up           GET  /v2/devices                     → unbind any device still listed (a previous run crashed)
4. Lookup             POST /v2/devices/lookup              → continue only on claimable / owned_by_me
5. Pair (BLE)         glassUserId + app cloud token        → handshake deviceToken
6. Bind               POST /v2/devices/bind                → device.id
7. Read version (BLE) GetVersionList                       → currentVersion
8. Check              GET  /v2/devices/{id}/firmware/check
9. Download           release.url                          → verify sha256
10. Flash + reconnect (BLE)
11. Report            POST /v2/devices/{id}/firmware/updates
12. Server unbind     POST /v2/devices/{id}/unbind
13. BLE unbind, remove bond, clear local device data
14. Sign out          POST /v2/auth/sign-out
```

- **Report before unbind.** After unbind the account no longer owns the device and the report returns `404 DEVICE_NOT_FOUND`.
- **Up to date / failure paths** still run steps 12–14 (and 11 if a release was offered).
- Step 3 exists because a crash between 6 and 12 leaves the device owned by the engineer account; the next customer would get `409 DEVICE_ALREADY_OWNED`.

---

## 5. Endpoint facts

### Sign-in and session
- `POST /v2/auth/sign-in/email { email, password }`. No `x-install-id` (§2).
- `GET /v2/auth/get-session` → `user.glassUserId`: a number the database assigns; nobody can set it.
- `POST /v2/auth/sign-out` → `{ success: true }`.

### Lookup
- `POST /v2/devices/lookup { macAddress }`. The MAC is normalized server-side; the OS address format is accepted.
- States: `unregistered`, `claimable`, `owned_by_me`, `owned_by_other`, `blocked`, `retired`.

| State | Tool behavior |
|---|---|
| `claimable`, `owned_by_me` | Continue |
| `unregistered` | Stop: glasses aren't registered in V2 |
| `owned_by_other` | Stop: glasses belong to another account |
| `blocked`, `retired` | Stop: glasses are blocked / retired |

### Bind
- Body: `macAddress` (required), `deviceToken`, `firmwareVersion`, `name`, `serialNumber`, `macAddressBt`, `os`, `frameVersion`, `modelCode` (all optional, strings). No `Idempotency-Key`, `cloud_token`, `claim` or `device_type`.
- **`deviceToken`** is the SE handshake response bytes **12–15 read as an unsigned 32-bit little-endian integer, sent as a decimal string** (1–20 digits). This is what the V2 SDK does (`packages/react-native-sdk/android/.../SeHandshake.kt`, `readU32Le(bytes, 12)` and `deviceToken.toString()`). A wrong format returns `422 DEVICE_TOKEN_INVALID`.
- Cloud token for pairing: generated in the app, `(unixSeconds & 0xFFFFFF) | 0xE0000000`, fresh on each pairing connect.
- **Send `modelCode`**, as `SKILL.md` §4 says. The server uses it only if the device has no model yet; without it, such a device stays without a model and the firmware check returns `unknown-model`.
- Read it from the glasses' BLE advertisement, as the V2 SDK does (`AdvertisementParser.kt`): the Manufacturer-Specific Data (AD type `0xFF`) blob starting with the literal bytes `02 15`; bytes 2–3 are the model code, big-endian, sent as 4 uppercase hex digits (e.g. `0007`). Use it only when the `02 15` prefix is present.
- On Android, walk the raw `ScanRecord.getBytes()` yourself: `getManufacturerSpecificData()` treats `02 15` as a company id and strips it.
- The current Android OTA tool doesn't read the advertisement yet; it must be added. If no code can be read, leave `modelCode` out rather than guessing one.
- Errors: `404 DEVICE_NOT_PROVISIONED`, `409 DEVICE_BLOCKED`, `409 DEVICE_ALREADY_OWNED`, `409 DEVICE_CONTENDED` (retry the same bind once, right away).

### Firmware check
- `GET /v2/devices/{id}/firmware/check?currentVersion=<version>`.
- `status`: `update-available`, `up-to-date`, `unknown-model`. (`update-blocked` and `no-firmware` are in the enum but never returned.)
- On `update-available`: `release { id, version, notes, sha256, sizeBytes, url, mandatory }` and `rules { minBattery, allowWhenCharging, inactivityTimeoutMs, maxDurationMs }`. Otherwise both are `null`.
- **A `currentVersion` that matches no release of the model returns `up-to-date`** (`lib/firmware-check.ts`). The V1 `currentVersion=0` trick no longer forces a reflash; remove it.
- Firmware is picked from the device's server-side model. The tool can't choose a brand's firmware line.
- `404 DEVICE_NOT_FOUND` for a device the account doesn't own (e.g. not bound yet).

### Download
- Use `release.url` directly; there's no download-link endpoint. It expires 15 minutes after the check. If the operator waits, check again before downloading.
- Use `sizeBytes` instead of a HEAD request. Verify the file's SHA-256 against `sha256`.
- Enforce `rules` before flashing (battery from the BLE battery command).

### Firmware update history
- `POST /v2/devices/{id}/firmware/updates { releaseId, status, error?, sdkVersion, startedAt, endedAt }`, once, at the end. → `{ id }`.
- `status`: `success`, `failed`, `cancelled`, `interrupted`. Suggested mapping: flash finished → `success`; error → `failed`; operator cancelled → `cancelled`; disconnect or reconnect timeout → `interrupted`.
- `sdkVersion`: required, 1–50 characters, e.g. `ota-tool/<app version>`.
- `startedAt`, `endedAt`: ISO-8601 instants. `error`: free text, up to 2000 characters.
- On `success` the server also updates the device's shown firmware version.
- `400 VALIDATION_FAILED` (`details: [{ field: "releaseId" }]`) if the release isn't the device model's.

### Unbind
- `POST /v2/devices/{id}/unbind`, no body (recorded as a plain user unbind). → `{ released }`. Don't send `cause: "factory_reset"`; the tool doesn't reset the glasses.

### Device events
- There is **no endpoint to write device events.** The server writes them itself: `bound` on bind, a release event on unbind, `rebind_rejected` when the glasses belong to another account.
- Send these headers on every request; the server stores them with each event, and `x-timezone` with each history row:

  | Header | Value |
  |---|---|
  | `x-client-brand` | Phone maker (Android `Build.MANUFACTURER`; iOS `"Apple"`) |
  | `x-client-model` | Phone model (Android `Build.MODEL`; iOS hardware identifier) |
  | `x-client-os` | e.g. `Android 15`, `iOS 18.1` |
  | `x-timezone` | IANA zone, e.g. `Asia/Colombo` |

---

## 6. Common mistakes

- Sending `x-install-id` from the tool (station phones sign each other out).
- Pairing before sign-in, or with a hardcoded user id instead of `glassUserId`.
- Unbinding on the server before sending the history report.
- Forgetting the server unbind, so the engineer account keeps customers' glasses.
- Keeping `currentVersion=0` to force a reflash (V2 answers `up-to-date`).
- Sending the brand code to the server.
- Downloading from a `release.url` older than 15 minutes.
- Sending the device token as hex, or reading the bytes big-endian.
- Leaving `modelCode` out of bind when the advertisement has one, or sending the brand code (`10`, `11`, …) as `modelCode`.
- Leaving the shared account's password in source code (rule 12): inject it at build time and rotate it.

---

## 7. Sources checked

V2 API (`thinkar-mono/thinkar/apps/api`, commit `7c40e4214`): `src/v2/device.ts`, `src/lib/firmware-check.ts`, `src/lib/device-scope.ts`, `src/lib/device-release.ts`, `src/lib/firmware-update-report.ts`, `src/lib/client-report.ts`, `src/lib/datetime.ts`, `src/lib/mac.ts`, `src/auth/one-phone.ts`, `src/auth/auth.ts`. SDK: `packages/react-native-sdk/android/src/main/java/com/thinkar/sdk/transport/protocol/SeHandshake.kt` and `AdvertisementParser.kt`. OTA tool: Android repo `OTA-Android` (commit `0c6e1ce`). The iOS OTA tool was not reviewed.
