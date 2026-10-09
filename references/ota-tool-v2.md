# ThinkAR OTA Tool → V2

The OTA tool is the internal firmware updater that staff use on customers' or stock glasses. It is **not** the customer app. It signs in with a shared engineer account, updates one pair of glasses, then releases them and signs out. It exists for Android and iOS; the flow and the V2 contract are the same on both.

Read this file **only** when the codebase is the OTA tool. Where it differs from `SKILL.md`, this file wins. Everything it doesn't mention (error format, camelCase bodies, string ids, no refresh) follows `SKILL.md`.

---

## 1. How to recognise it

The codebase is the OTA tool if most of these hold:

- Its only server calls are sign-in, token refresh, `firmware/latest/{code}`, `firmware/download/{id}` and `firmware/update-log` (create + update). No live agent, translation, profile or device list.
- The operator types a **brand verification code** (`AISIN`, `Appoconn`, `CASALIZ`, `THINKAR`) that maps to a firmware code (`10`, `11`, `13`, `0`). The firmware code is the **major version** of that brand's firmware (`10.x.y` for AISIN).
- It signs in with **one fixed engineer account**, not a user-entered account.
- BLE pairing uses a **hardcoded glasses user id** (`23412` on Android and iOS) and a cloud token generated in the app.
- It forces a reflash by sending `currentVersion=0` when the glasses' major version doesn't match the brand code (or when the debug switch `SentryTelemetryConfig.FORCE_UPDATE` is on). In effect this **converts** glasses to the typed brand: the server returns that brand's newest firmware and the tool flashes it.
- After an update (or "already latest"), it sends the BLE **unbind** command, removes the OS Bluetooth bond, clears local device data and signs out.

Android reference points (package `com.thinkar.ota`):

| File | What it holds |
|---|---|
| `api/API.kt` | V1 base URL and paths |
| `api/BaseRequest.kt` | Bearer header, pre-request refresh (`refreshTokenIfNeed`), no 401 handling |
| `api/Session.kt` | `SessionManager`: access/refresh token, `expiresAt`, user id |
| `api/*Request.kt` | Sign-in, refresh, firmware latest, download link, update-log create/patch |
| `verification/VerificationFragment.kt` | Brand codes, **hardcoded engineer credentials**, sign-in, version read, `currentVersion=0`, up-to-date clean-up |
| `ble/GlassesService.kt` | Scan (`startScan`, `scanCallback`), post-flash reconnect with the saved retrieve token |
| `ble/AiLens.kt` | Pairing user id `23412`, cloud token, handshake `deviceToken` (bytes 12–15), `completeConnection` saves device info |
| `TokenManager.kt` | Pairing token and retrieve token, both built from the user id |
| `SharedPrefs.kt` | Saved device info (MAC, retrieve token); `MainActivity` clears it on every launch unless an update is running |
| `ble/FirmwareManager.kt` | Firmware check, download link, HEAD for size, download cache `ota/glass/<version>/ota.bin` |
| `ble/FirmwareUpdateLogger.kt` | V1 update log (`begin` / `success` / `failed`) |
| `ble/FirmwareUpdateService.kt` | `startFullUpdate` (download → transfer → reconnect → `performUnbindAndCleanup`) |
| `ble/command/ota/GetVersionListCommand.kt` | Glasses version, `major.minor.patch` of entry type `0x20` |

iOS reference points (`OTA-iOS`, target `OTA`; plain CoreBluetooth, **not** the vendor `XRBluetooth` SDK):

| File | What it holds |
|---|---|
| `API/API.swift` | V1 base URL and paths (no refresh path) |
| `API/BaseReuqest.swift` | Bearer header; `refreshTokenIfNeed` is empty; **retries every request 3 times on any error, 4xx included** |
| `API/SessionManager.swift` | Keychain: access/refresh token, `expiresAt`, user id |
| `API/*Request.swift` | Sign-in, firmware latest, download link, update-log create/patch |
| `Verification/VerificationViewController.swift` | Brand codes, **hardcoded engineer credentials**, sign-in, version read, `currentVersion=0` (`SentryTelemetryConfig.forceUpdate`), up-to-date clean-up |
| `Bluetooth/GlassesService.swift` | `userId = 23412`; scan by service UUID; `shouldDiscover` parses the advertisement (`02 15` prefix, MAC = bytes 4–9); post-flash reconnect with the saved retrieve token |
| `Bluetooth/AiLens.swift` | Handshake `deviceToken` (bytes 12–15, little-endian `UInt32`), saves the retrieve token |
| `Bluetooth/TokenManager.swift` | Pairing and retrieve token from the user id; `fetchCloudToken` (local generation, with a stale TODO naming `/api/v2/terminals/check`) |
| `SceneDelegate.swift` | On every launch: clears the saved device info **and** signs out |
| `OTA/FirmwareManager.swift` | Firmware check, download link, HEAD for size, download cache `ota/<dir>/<version>/ota.bin` |
| `OTA/OTAViewController.swift` | Downloads the firmware, then calls `FirmwareUpdateService.startUpdate` |
| `OTA/FirmwareUpdateLogger.swift` | V1 update log (`begin` / `success` / `failed`); begins after the download |
| `OTA/FirmwareUpdateService.swift` | Transfer → `success()` → reconnect → `performUnbindAndCleanup` (BLE unbind, sign out; iOS can't remove a bond) |
| `Command/AiLens/OTA/GetFirmwareVersionCommand.swift` | Glasses version, `major.minor.patch` of entry type `0x20` |

**V1 screen order (Android and iOS):** scan → pair → brand-code screen → sign in → read version → check. V2 needs the account (for `glassUserId`) **before** pairing, so sign-in and the brand code move in front of scanning (§4).

**What the tools do today that matters for V2** (both platforms unless marked):
- They sign in fresh on every run, so a `401` mid-run is rare; there is no 401 handling to port. iOS has no refresh at all (`refreshTokenIfNeed` is empty).
- Android: the scan filter is `ScanFilter.setManufacturerData(5378, byteArrayOf(0x00, 0x00))` (`5378` = `0x1502`, the `02 15` prefix read as a company id). It only lists glasses whose model code is **`0000`**, so every brand it updates today reports `0000`. Keep the filter (rule 11).
- iOS: scans by service UUID and lists **any** model code. It only knows the MAC when the advertisement has the `02 15` prefix; otherwise `mac` is empty and logs fall back to `peripheral.identifier`.
- iOS: `BaseRequest` retries every request 3 times, even after a `4xx`. In V2, retry only network failures and never a `4xx`: a retried `POST …/firmware/updates` writes a second history row, and a retried `409`/`404` can't succeed.
- iOS: `API.domain` ends in `/` and the paths start with `/`, so every URL has `//api/v1`. Build the V2 base URL without a trailing slash.
- It never verifies `sha256` and never checks battery. V2 gives both; add them (§5).
- There is no cancel control: `FirmwareUpdateService.stopUpdate()` has no caller on either platform.
- On failure they show the failed screen and keeps the glasses paired and the session open; only success and up-to-date run the clean-up.

---

## 2. Where it differs from `SKILL.md`

| `SKILL.md` | OTA tool |
|---|---|
| Send `x-install-id` on every sign-in (one phone per account) | **Don't send it.** Many station phones share one account. Only sessions that carry an install id sign out older phones (`auth/one-phone.ts`), so leaving it out keeps every phone signed in |
| The user keeps the device after bind | **Release it** at the end of every run: report → server unbind → BLE unbind → remove bond (Android only; iOS can't) → sign out |
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
15. BLE unbind, remove bond (Android), clear local device data
16. Sign out            POST /v2/auth/sign-out
```

- **Report before unbind.** After unbind the account no longer owns the device and the report returns `404 DEVICE_NOT_FOUND`.
- **Up to date, refused, cancelled and failure paths** still run steps 14–16 (and 13 if a release was offered). Step 14 must not depend on the BLE unbind working: glasses that failed mid-flash may not answer BLE.
- **Store the crash-recovery record on its own.** Android `MainActivity` calls `SharedPrefs.clearDeviceInfo()` on every launch, and iOS `SceneDelegate` calls `removeLastDeviceInfo()` and `SessionManager.logout()` on every launch. Don't keep it in the saved device info, and on start-up sign in first (step 1) before step 4 uses it.
- **Step 4 never unbinds anything this phone didn't bind.** All station phones share one account, so `GET /v2/devices` also lists glasses that *other* stations are updating right now. Unbinding those breaks their run (their report and check return `404 DEVICE_NOT_FOUND`). Save the bound device id (and, once offered, the `releaseId` and `startedAt`) in local storage at step 9, clear it after step 14, and on start-up release only that saved id. A device left bound by a phone that was wiped or replaced is released by staff from the dashboard.
- **Step 8 before step 9**: bind takes `firmwareVersion`, so read it first.
- **Brand conversion is gone.** If the glasses' major version doesn't match the brand code, stop with "These glasses are not <brand>". V2 can't force a reflash (§5), so the V1 conversion (and the `FORCE_UPDATE` switch) can't be ported. Add `TODO(v2-migration): needs manual review — V1 converted glasses to another brand via currentVersion=0; V2 has no equivalent` and list it in the report (rule 13: confirm with the user before removing the path).

---

## 5. Endpoint facts

### Sign-in and session
- `POST /v2/auth/sign-in/email { email, password }`. No `x-install-id` (§2).
- `GET /v2/auth/get-session` → `user.glassUserId`: a number the database assigns; nobody can set it.
- `POST /v2/auth/sign-out` → `{ success: true }`.

### Lookup
- `POST /v2/devices/lookup { macAddress }`. The MAC is normalized server-side; the OS address format is accepted.
- **iOS has no OS MAC address.** CoreBluetooth only gives `peripheral.identifier` (a UUID), which the server rejects (`400 VALIDATION_FAILED`). Use the MAC that `GlassesService.shouldDiscover` already parses from the advertisement (bytes 4–9). If the advertisement has no `02 15` prefix (empty `mac`), stop with "Can't read this pair's address; move closer and scan again". Send the same MAC to bind.
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
- Cloud token for pairing: generated in the app, `(unixSeconds & 0xFFFFFF) | 0xE0000000`, fresh on each pairing connect. (Android already does this: each scan result builds a new `AiLens`.)
- **Replace `23412` everywhere it is used, not only for pairing.** `AiLens.userId` feeds both the pairing token (`TokenManager.createConnectionToken`) and the saved retrieve token (`SharedPrefs.saveDeviceInfo` → `TokenManager.getRetrieveToken`) that `GlassesService` uses to reconnect after the flash. Both must use the same `glassUserId`, or the post-flash reconnect is rejected. Persist `glassUserId` with the session: `FirmwareUpdateService` runs as a foreground service and can outlive the screen that signed in.
  - iOS: the same applies to `GlassesService.userId` (`23412`), which feeds `AiLens` pairing and `TokenManager.saveRetrieveToken`.
- iOS `TokenManager.fetchCloudToken` already generates the cloud token locally. Keep it and delete its TODO: there is no server cloud token in V2 (no `/api/v2/terminals/check`).
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

- **Android:** read it from the BLE advertisement, as the V2 SDK does (`AdvertisementParser.kt`): the Manufacturer-Specific Data (AD type `0xFF`) blob starting with the literal bytes `02 15`; bytes 2–3 are the model code, big-endian, formatted `"%04X"`. Use it only when the `02 15` prefix is present. Walk the raw `ScanRecord.getBytes()` yourself: `getManufacturerSpecificData()` treats `02 15` as a company id and strips it. The current Android OTA tool doesn't read the advertisement yet: in `GlassesService.scanCallback.onScanResult`, parse `result.scanRecord?.bytes` and keep the code with the `AiLens` for that MAC. With today's scan filter it is always `0000`.
- **iOS:** the OTA tool uses plain CoreBluetooth. `advertisementData[CBAdvertisementDataManufacturerDataKey]` keeps the `02 15` prefix (iOS doesn't strip it), so in `GlassesService.shouldDiscover`, next to the MAC, read bytes 2–3 as `String(format: "%02X%02X", bytes[2], bytes[3])` and keep it with the `AiLens`. Only when the prefix is present. (An app built on the vendor `XRBluetooth` SDK gets the same 4-digit code from `XRDeviceModel.rawValue`, e.g. `XRDeviceModelG07S5` = `"0007"`.)
- If no code can be read, leave `modelCode` out rather than guessing one. Never send the brand code (`10`, `11`, …).

### Firmware check
- `GET /v2/devices/{id}/firmware/check?currentVersion=<version>`.
- `status`: `update-available`, `up-to-date`, `unknown-model`. (`update-blocked` and `no-firmware` are in the enum but never returned.)
- On `update-available`: `release { id, version, notes, sha256, sizeBytes, url, mandatory }` and `rules { minBattery, allowWhenCharging, inactivityTimeoutMs, maxDurationMs }`. Otherwise both are `null`.
- **`currentVersion` must be the exact version string of a release the server holds for that model** (`lib/firmware-check.ts` matches the string, then compares build numbers). A version that matches no release returns `up-to-date`, silently. So:
  - Send the version exactly as `GetVersionList` returns it; don't reformat it.
  - The V1 `currentVersion=0` trick no longer forces a reflash; remove it (and the `FORCE_UPDATE` switch that feeds it).
- **Brand guard.** Firmware is picked from the device's server-side model, not the brand. Glasses of different brands share one model code: every brand the Android tool updates today reports `0000` (the iOS tool lists any model, but the same brands report the same code), so on the server they are all one model (Bach), and the newest build of that model wins whatever its major version. The server-side fix is for staff to give each brand's releases `upgradeScope` `minor` or `patch` (both keep the same major version; the default `any` doesn't) — report this as a manual-review item. In the tool, before downloading, check that the major version of `release.version` equals the brand code. If not, don't flash: report nothing, run steps 14–16, and tell the operator "The server offered <version>, which is not <brand> firmware. Ask staff to check the device's model."
- `unknown-model`: stop with "These glasses have no model on the server. Ask staff to link model code <code>."
- `404 DEVICE_NOT_FOUND` for a device the account doesn't own (e.g. not bound yet).

### Download
- Use `release.url` directly; there's no download-link endpoint. It expires 15 minutes after the check. If the operator waits, check again before downloading.
- Use `sizeBytes` instead of the HEAD request (`FirmwareManager.getFileSizeFromURL`). Verify the file's SHA-256 against `sha256`.
- The Android tool reuses a cached file at `ota/glass/<version>/ota.bin` without downloading. Verify `sha256` on the cached file too, and download again on a mismatch.
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
  | Operator cancelled (only if the tool has a cancel control; Android has none today — don't add one) | `cancelled` |
  | Any other error (download, sha256 mismatch, BLE command) | `failed` |

- `sdkVersion`: required, 1–50 characters, e.g. `ota-tool/<app version>`.
- `startedAt`, `endedAt`: ISO-8601 instants with an offset (`2026-10-09T08:15:00Z`). `startedAt` is when the download starts (on iOS the V1 log only began after the download). `error`: free text, up to 2000 characters.
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
- Replacing `23412` for pairing but not in the saved retrieve token (the post-flash reconnect fails).
- Keeping the crash-recovery record in the saved device info (Android `MainActivity` and iOS `SceneDelegate` wipe it on launch).
- iOS: sending `peripheral.identifier` as `macAddress`, or keeping `BaseRequest`'s retry of `4xx` responses.
- iOS: implementing the old `fetchCloudToken` TODO against a server endpoint.
- Flashing a cached firmware file without checking its `sha256`.
- Leaving the shared account's password in source code (rule 12): inject it at build time and rotate it.

---

## 7. Sources checked

V2 API (`thinkar-mono/thinkar/apps/api`, commit `a4a3c2502`): `src/v2/device.ts`, `src/lib/firmware-check.ts`, `src/lib/device-scope.ts`, `src/lib/model-code-resolver.ts`, `src/lib/device-release.ts`, `src/lib/firmware-update-report.ts`, `src/lib/legacy-ownership-sync.ts`, `src/lib/client-report.ts`, `src/lib/datetime.ts`, `src/lib/mac.ts`, `src/auth/one-phone.ts`, `src/auth/auth.ts`, `src/middleware/auth.ts`. SDK: `packages/react-native-sdk/android/.../SeHandshake.kt`, `AdvertisementParser.kt`, `src/capabilities/modelCode.ts`, `ios/ThinkARSDK/Core/BLE/XRBluetoothBridge.swift`, `docs/xrbluetooth-internals.md` §4.1. Production model codes (`0000`, `000A`, `0007`, …) confirmed by the API team; the dev seed (`packages/db/src/dev-seed.ts`) uses placeholder codes and is not the reference. OTA tool: Android repo `OTA-Android` (commit `0c6e1ce`), all files in the table in §1 plus `MainActivity.kt`, `ota/OTAFragment.kt` and the navigation graphs. iOS repo `OTA-iOS` (commit `a2420d2`), all files in the iOS table in §1 plus `App Navigation/AppCoordinator.swift`, `Add Device/*` and `Command/AiLens/GetMacAddressCommand.swift` (present but unused).
