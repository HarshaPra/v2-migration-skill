# ThinkAR OTA Tool → V2

The OTA tool is the internal firmware updater that staff use on customers' or stock glasses. It is **not** the customer app. It signs in with a shared engineer account, updates one pair of glasses, then releases them and signs out. It exists for Android and iOS; the flow and the V2 contract are the same on both.

Read this file **only** when the codebase is the OTA tool. Where it differs from `SKILL.md`, this file wins. Everything it doesn't mention (error format, camelCase bodies, string ids, no refresh) follows `SKILL.md`.

---

## 1. How to recognise it

The codebase is the OTA tool if most of these hold:

- Its only server calls are sign-in, token refresh, `firmware/latest/{code}`, `firmware/download/{id}` and `firmware/update-log` (create + update). No live agent, translation, profile or device list.
- The operator types a **brand verification code** (`AISIN`, `Appoconn`, `CASALIZ`, `THINKAR`) that maps to a firmware code (`10`, `11`, `13`, `0`). The firmware code is the **major version** of that brand's firmware (`10.x.y` for AISIN).
- It signs in with **one fixed engineer account**, not a user-entered account.
- BLE pairing uses a **hardcoded glasses user id** (Android: `23412`) and a cloud token generated in the app.
- It forces a reflash by sending `currentVersion=0` when the glasses' major version doesn't match the brand code.
- After an update (or "already latest"), it sends the BLE **unbind** command, removes the OS Bluetooth bond, clears local device data and signs out.

Android reference points (package `com.thinkar.ota`): `api/API.kt`, `api/BaseRequest.kt`, `api/Session.kt`, `verification/VerificationFragment.kt` (brand codes, sign-in, version check), `ble/AiLens.kt` (pairing user id and cloud token), `ble/FirmwareManager.kt`, `ble/FirmwareUpdateLogger.kt`, `ble/FirmwareUpdateService.kt` (`startFullUpdate`, `performUnbindAndCleanup`). On iOS, find the equivalents by behavior.

**V1 screen order (Android):** scan → pair → brand-code screen → sign in → read version → check. V2 needs the account (for `glassUserId`) **before** pairing, so sign-in and the brand code move in front of scanning (§4).

---

## 2. Where it differs from `SKILL.md`

| `SKILL.md` | OTA tool |
|---|---|
| Send `x-install-id` on every sign-in (one phone per account) | **Don't send it.** Many station phones share one account. Only sessions that carry an install id sign out older phones (`auth/one-phone.ts`), so leaving it out keeps every phone signed in |
| The user keeps the device after bind | **Release it** at the end of every run: report → server unbind → BLE unbind → remove bond → sign out |
| Pair only after `lookup` says `claimable` / `owned_by_me` | Same, but a non-claimable state ends the run with a message to the operator |
| Firmware model chosen by the server | Same. The brand code is **app-side only**: it is never sent to the server, and it guards both the glasses' version and the offered release (§5, Firmware check) |
| 401 → go to sign-in | The tool signs in itself: clear the session and sign in again once. Still no refresh flow |
| `403 AUTH_MUST_CHANGE_PASSWORD` → change-password screen | The tool has no such screen. Stop with "The engineer account must change its password in the dashboard". Make sure the shared account is not on a temporary password before rollout |

---

## 3. V1 → V2 mapping

| V1 | V2 | Notes |
|---|---|---|
| `POST /api/v1/auth/signin` | `POST /v2/auth/sign-in/email { email, password }` | Store the body `token` only, as Bearer |
| `GET /api/v1/auth/refresh` | — | Remove. Delete refresh token, `expiresAt` and the pre-request refresh |
| sign-in `user.session.userId` | `GET /v2/auth/get-session` → `user.id` (UUID), `user.glassUserId` (number) | |
| hardcoded BLE user id | `user.glassUserId` | Sign in **before** pairing, so the id is known |
| — (no server call) | `POST /v2/devices/lookup { macAddress }` | New. Before pairing |
| — (no server call) | `POST /v2/devices/bind { macAddress, deviceToken, modelCode, firmwareVersion, name? }` | New. After the BLE handshake and version read. Keep the returned `id` |
| `GET /api/v1/firmware/latest/{code}?currentVersion&deviceType` | `GET /v2/devices/{id}/firmware/check?currentVersion=` | By bound device id. Send the glasses' **real** version, never `0` |
| `GET /api/v1/firmware/download/{id}` → `download_url` | `release.url` from the check | Valid 15 minutes |
| `POST` + `PATCH /api/v1/firmware/update-log` | `POST /v2/devices/{id}/firmware/updates` | One report at the end, after reconnect |
| BLE unbind only | `POST /v2/devices/{id}/unbind`, then BLE unbind | New server step |
| local logout | `POST /v2/auth/sign-out`, then clear local state | |

Base URL: one `https://<host>/v2` constant per environment.

---

## 4. Run flow

```
1.  Sign in             POST /v2/auth/sign-in/email          → token
2.  Session             GET  /v2/auth/get-session            → user.glassUserId
3.  Brand code          operator types it                    → firmware major (10 / 11 / 13 / 0)
4.  Recover own crash   only the device id THIS phone saved  → report (if pending) + unbind it, then forget it
5.  Scan (BLE)          advertisement                        → MAC + modelCode
6.  Lookup              POST /v2/devices/lookup              → continue only on claimable / owned_by_me
7.  Pair (BLE)          glassUserId + app cloud token        → handshake deviceToken
8.  Read version (BLE)  GetVersionList                       → currentVersion (check major == brand code)
9.  Bind                POST /v2/devices/bind                → device.id  (save it locally at once)
10. Check               GET  /v2/devices/{id}/firmware/check → check release major == brand code
11. Download            release.url                          → verify sizeBytes + sha256
12. Flash + reconnect (BLE), re-read version if reconnected
13. Report              POST /v2/devices/{id}/firmware/updates
14. Server unbind       POST /v2/devices/{id}/unbind         → forget the saved device id
15. BLE unbind, remove bond, clear local device data
16. Sign out            POST /v2/auth/sign-out
```

- **Report before unbind.** After unbind the account no longer owns the device and the report returns `404 DEVICE_NOT_FOUND`.
- **Up to date, refused, cancelled and failure paths** still run steps 14–16 (and 13 if a release was offered). Step 14 must not depend on the BLE unbind working: glasses that failed mid-flash may not answer BLE.
- **Step 4 never unbinds anything this phone didn't bind.** All station phones share one account, so `GET /v2/devices` also lists glasses that *other* stations are updating right now. Unbinding those breaks their run (their report and check return `404 DEVICE_NOT_FOUND`). Save the bound device id (and, once offered, the `releaseId` and `startedAt`) in local storage at step 9, clear it after step 14, and on start-up release only that saved id. A device left bound by a phone that was wiped or replaced is released by staff from the dashboard.
- **Step 8 before step 9**: bind takes `firmwareVersion`, so read it first. If the glasses' major version doesn't match the brand code, stop with "These glasses are not <brand>" — V2 can't force a reflash (§5).

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
| `owned_by_other` | Stop: "These glasses are linked to a customer account. Ask the customer to remove them in the app, or ask staff to release them in the dashboard." |
| `blocked`, `retired` | Stop: glasses are blocked / retired |

- **`owned_by_other` is the common case for customer glasses.** The V1 → V2 import and the legacy ownership sync (`apps/api/src/lib/legacy-ownership-sync.ts`) bind each customer's glasses to their V2 account. V2 has no staff or engineer route that can bind or update a device another account owns. Don't work around it (no force unbind, no retry loop). Add `TODO(v2-migration): needs manual review — OTA tool cannot update customer-owned glasses; needs a product decision (customer unbinds first / staff release in dashboard / new staff endpoint)` and list it in the report.

### Bind
- Body: `macAddress` (required), `deviceToken`, `firmwareVersion`, `name`, `serialNumber`, `macAddressBt`, `os`, `frameVersion`, `modelCode` (all optional, strings). No `Idempotency-Key`, `cloud_token`, `claim` or `device_type`.
- **`deviceToken`** is the SE handshake response bytes **12–15 read as an unsigned 32-bit little-endian integer, sent as a decimal string** (1–20 digits). This is what the V2 SDK does (`packages/react-native-sdk/android/.../SeHandshake.kt`, `readU32Le(bytes, 12)` and `deviceToken.toString()`). A wrong format returns `422 DEVICE_TOKEN_INVALID`.
- Cloud token for pairing: generated in the app, `(unixSeconds & 0xFFFFFF) | 0xE0000000`, fresh on each pairing connect.
- Errors: `404 DEVICE_NOT_PROVISIONED`, `409 DEVICE_BLOCKED`, `409 DEVICE_ALREADY_OWNED`, `409 DEVICE_CONTENDED` (retry the same bind once, right away).

### Model code
- **Send `modelCode`**, as `SKILL.md` §4.1 says. The server uses it only if the device has no model yet (an imported device already has one); without it, such a device stays without a model and the firmware check returns `unknown-model`.
- **Format: exactly 4 uppercase hex digits** — the last 4 digits of the advertised code, e.g. `0007`. The server only trims and upper-cases it, then needs an **exact** match in its model-code list (`lib/model-code-resolver.ts`). It does **not** remove a `02 15` prefix, a `0x` prefix, or add leading zeros: `0215000A`, `0x0007` and `7` all resolve to no model.

  | Code | Model | | Code | Model |
  |---|---|---|---|---|
  | `0000` | Bach | | `0007` | G07S5 (Ultra) |
  | `0002` | Picasso | | `0008` | G12S0 |
  | `0003` | Mozart | | `0009` | G07S3 |
  | `0004` | Handel | | `000A` | G09 (also G09 NBA) |
  | `0005` | G12X1 | | `0100` | Ring (not glasses) |

- **Android:** read it from the BLE advertisement, as the V2 SDK does (`AdvertisementParser.kt`): the Manufacturer-Specific Data (AD type `0xFF`) blob starting with the literal bytes `02 15`; bytes 2–3 are the model code, big-endian, formatted `"%04X"`. Use it only when the `02 15` prefix is present. Walk the raw `ScanRecord.getBytes()` yourself: `getManufacturerSpecificData()` treats `02 15` as a company id and strips it. The current Android OTA tool doesn't read the advertisement yet; it must be added at scan time (step 5) and kept per MAC.
- **iOS:** the vendor SDK's `XRDeviceModel` value is already the 4-digit code (`XRDeviceModelG07S5` = `"0007"`); the V2 SDK sends `device.model.rawValue` (`XRBluetoothBridge.modelCodeOf`). Don't send it when the model is unknown / unverified.
- If no code can be read, leave `modelCode` out rather than guessing one. Never send the brand code (`10`, `11`, …).

### Firmware check
- `GET /v2/devices/{id}/firmware/check?currentVersion=<version>`.
- `status`: `update-available`, `up-to-date`, `unknown-model`. (`update-blocked` and `no-firmware` are in the enum but never returned.)
- On `update-available`: `release { id, version, notes, sha256, sizeBytes, url, mandatory }` and `rules { minBattery, allowWhenCharging, inactivityTimeoutMs, maxDurationMs }`. Otherwise both are `null`.
- **`currentVersion` must be the exact version string of a release the server holds for that model** (`lib/firmware-check.ts` matches the string, then compares build numbers). A version that matches no release returns `up-to-date`, silently. So:
  - Send the version exactly as `GetVersionList` returns it; don't reformat it.
  - The V1 `currentVersion=0` trick no longer forces a reflash; remove it (and the `FORCE_UPDATE` switch that feeds it).
- **Brand guard.** Firmware is picked from the device's server-side model, not the brand. Glasses of different brands can share one model code (e.g. `0007`), so before downloading, check that the major version of `release.version` equals the brand code. If not, don't flash: report nothing, run steps 14–16, and tell the operator "The server offered <version>, which is not <brand> firmware. Ask staff to check the device's model."
- `unknown-model`: stop with "These glasses have no model on the server. Ask staff to link model code <code>."
- `404 DEVICE_NOT_FOUND` for a device the account doesn't own (e.g. not bound yet).

### Download
- Use `release.url` directly; there's no download-link endpoint. It expires 15 minutes after the check. If the operator waits, check again before downloading.
- Use `sizeBytes` instead of a HEAD request. Verify the file's SHA-256 against `sha256`.
- Enforce `rules` before flashing (battery from the BLE battery command). Use `maxDurationMs` as the limit for one attempt.

### Firmware update history
- `POST /v2/devices/{id}/firmware/updates { releaseId, status, error?, sdkVersion, startedAt, endedAt }`, **once**, after the flash **and** the reconnect wait. → `{ id }`. Replaces both V1 calls: delete `logger.begin()` / `success()` / `failed()` (V1 marked success before the reconnect).
- `status`: `success`, `failed`, `cancelled`, `interrupted`:

  | What happened | `status` |
  |---|---|
  | Transfer finished, glasses reconnected (and, if read, report `release.version`) | `success` |
  | Transfer finished, glasses reconnected but report a different version | `failed`, `error` = both versions |
  | Transfer finished, reconnect timed out | `interrupted`, `error` = "reconnect timeout" |
  | Disconnect during download or transfer | `interrupted` |
  | Operator cancelled | `cancelled` |
  | Any other error (download, sha256 mismatch, BLE command) | `failed` |

- `sdkVersion`: required, 1–50 characters, e.g. `ota-tool/<app version>`.
- `startedAt`, `endedAt`: ISO-8601 instants with an offset (`2026-10-09T08:15:00Z`). `error`: free text, up to 2000 characters.
- On `success` the server also updates the device's shown firmware version.
- `400 VALIDATION_FAILED` (`details: [{ field: "releaseId" }]`) if the release isn't the device model's.
- If the app dies between flash and report, step 4 on the next start sends the pending report as `interrupted` before unbinding.

### Unbind
- `POST /v2/devices/{id}/unbind`, no body (recorded as a plain user unbind). → `{ released }`. `released: false` means it was already free (safe retry). Don't send `cause: "factory_reset"`; the tool doesn't reset the glasses.

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
- Unbinding every device in `GET /v2/devices` at start-up (it releases glasses other stations are updating).
- Unbinding on the server before sending the history report.
- Forgetting the server unbind, or skipping it because the BLE unbind failed, so the engineer account keeps customers' glasses.
- Reporting `success` before the glasses reconnect.
- Keeping `currentVersion=0` to force a reflash (V2 answers `up-to-date`).
- Reformatting the glasses' version string before the check (no match → `up-to-date`).
- Flashing a release whose major version isn't the brand code.
- Sending the brand code to the server.
- Downloading from a `release.url` older than 15 minutes.
- Sending the device token as hex, or reading the bytes big-endian.
- Leaving `modelCode` out of bind when the advertisement has one; sending it with the `02 15` prefix (`0215000A`), a `0x` prefix, lower-case or without leading zeros; or sending the brand code (`10`, `11`, …) as `modelCode`.
- Working around `owned_by_other` instead of stopping and reporting it.
- Leaving the shared account's password in source code (rule 12): inject it at build time and rotate it.

---

## 7. Sources checked

V2 API (`thinkar-mono/thinkar/apps/api`, commit `a4a3c2502`): `src/v2/device.ts`, `src/lib/firmware-check.ts`, `src/lib/device-scope.ts`, `src/lib/model-code-resolver.ts`, `src/lib/device-release.ts`, `src/lib/firmware-update-report.ts`, `src/lib/legacy-ownership-sync.ts`, `src/lib/client-report.ts`, `src/lib/datetime.ts`, `src/lib/mac.ts`, `src/auth/one-phone.ts`, `src/auth/auth.ts`, `src/middleware/auth.ts`. SDK: `packages/react-native-sdk/android/.../SeHandshake.kt`, `AdvertisementParser.kt`, `src/capabilities/modelCode.ts`, `ios/ThinkARSDK/Core/BLE/XRBluetoothBridge.swift`, `docs/xrbluetooth-internals.md` §4.1. Production model codes (`0000`, `000A`, `0007`, …) confirmed by the API team; the dev seed (`packages/db/src/dev-seed.ts`) uses placeholder codes and is not the reference. OTA tool: Android repo `OTA-Android` (commit `0c6e1ce`). The iOS OTA tool was not reviewed.
