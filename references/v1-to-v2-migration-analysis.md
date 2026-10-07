# V1 → V2 Migration Analysis

This document is the analysis behind the developer migration guide. It lists exactly what an existing V1 client must change to work with V2.

**References**
- `V1 §n` → `v1-api-endpoints.md`, section *n*
- `V2 §x` → `v2-technical-inventory.md`, section *x*
- **Needs manual review** marks an item that can't be mapped with confidence from the two inventories. It needs a product or engineering decision before the guide is written.

---

## 1. Authentication Migration

### 1.1 Side-by-side
| Topic | V1 | V2 | Ref |
|---|---|---|---|
| Credential | JWT access token + refresh token | Opaque **session token** (server-side session). JWTs are not accepted on resource routes | V1 §2 · V2 §A.1 |
| Login (password) | `POST /api/v1/auth/signin` → tokens in body (`accessToken`, `refreshToken`, `expiresIn`, `expiresAt`) | `POST /v2/auth/sign-in/email` → `token` in body **and** `set-auth-token` header; browsers also get a cookie | V1 §3 · V2 §A.2–A.3 |
| Login (social) | `POST /api/v1/auth/signin-oauth` `{provider, idToken, nonce}` | `POST /v2/auth/sign-in/social` `{provider, idToken:{token, nonce}}` | V1 §3 · V2 §A.3 |
| Login (email code) | `send-otp` + `verify-otp` (`type: magiclink`/`email`) | `email-otp/send-verification-otp` (`type: "sign-in"`) + `sign-in/email-otp`, or the magic-link flow | V1 §3 · V2 §A.3 |
| Logout | `POST /auth/signout`. The server doesn't revoke the token; the client discards it | `POST /v2/auth/sign-out`. **The session is deleted on the server** and the token stops working | V1 §3 · V2 §A.4 |
| Token transport (native) | `Authorization: Bearer <JWT>` | `Authorization: Bearer <session token>` (same header, different token) | V1 §2 · V2 §A.1, F.1 |
| Token transport (browser) | `Authorization` header; cookies not used | **Session cookie** (`HttpOnly`, `SameSite=Lax`, `Secure` on HTTPS) with `credentials: "include"` | V1 §2 · V2 §A.7, F.3 |
| Cookies | Not used | `__Secure-better-auth.session_token` (HTTPS), 7-day max-age | V1 §2 · V2 §A.7 |
| Session state | Stateless JWT | Server-side; ended by sign-out, a password reset, account deletion, or a newer phone sign-in | V2 §A.5–A.6 |
| Expiration | `expiresIn` / `expiresAt` returned. The client refreshes before expiry | 7 days, **sliding** (extended daily with use). No expiry fields to track | V1 §2 · V2 §A.6 |
| Refresh | `POST /auth/refresh` `{code: refresh_token}`, returns a new refresh token each time | **None** | V1 §3 · V2 §A.6 |
| Extra auth headers | none | `x-install-id` (UUID per install) on sign-in, which enables one phone per account | V2 §A.5, D.4 |
| Unauthorized (HTTP) | `401 {statusCode, message: "Unauthorized"}` | `401 {error:{code:"UNAUTHENTICATED", status, message}}`. Also `401 ACCOUNT_DELETED_BY_ADMIN` and `403 AUTH_MUST_CHANGE_PASSWORD` | V1 §2 · V2 §A.11, A.6 |
| Unauthorized (real-time) | Not described in V1 §8/§9 beyond token checks | WS close `4401`; Socket.IO `connect_error`; `session_revoked` mid-call | V2 §A.11, E.4 |
| Rate limits | Not described in V1 docs | Per-endpoint limits on auth; `429 RATE_LIMITED` + `retry-after` | V2 §A.12 |
| Client config | One base URL `/api/v1`, plus a **separate translation host** | One host. `/v2` for REST, `/v2/*/live` for WebSockets, `/socket.io/` for `/live-agent` | V1 §1, §9 · V2 §B |

### 1.2 Moving from V1 JWT auth to V2 session auth
V2 uses **cookies for browsers** and a **Bearer session token for native and server clients**. Both identify the same server-side session. Mobile apps do **not** switch to cookies.

**All clients**
1. Remove the V1 token model.
   - Delete stored `accessToken`, `refreshToken` and `expiresAt`.
   - Delete the refresh call and any timer that refreshes before expiry (V1 §3 `/auth/refresh` → V2 §A.6 "no refresh").
2. Replace the login calls with the V2 endpoints (§2 of this doc). V1 tokens aren't valid in V2, so **every user signs in once after the switch**.
   - Existing V1 accounts and glasses bindings are available in V2, and V1 credentials keep working.
   - Account exceptions:
     - Expired temporary password → password reset.
     - Email never verified → `AUTH_EMAIL_NOT_VERIFIED` until verified.
     - Inactive or banned → `AUTH_ACCOUNT_BANNED`.
     - Deleted, anonymous, no email, or a duplicate email → not available.
   - Binding exceptions:
     - Invalid owner or not in an owned state → unowned.
     - Token not 1–20 digits → no token stored.
     - Decommissioned → `retired`.
3. Replace "refresh on expiry" with "**sign in again on 401**". A V2 session can end at any time: sign-out, a password reset, account deletion, or another phone signing in (V2 §A.6).
4. Handle the new auth error codes (§5 of this doc).

**Native / mobile**

5. Read the token from the `set-auth-token` response header, or the body `token`. They're different strings (signed vs plain), but both work as Bearer. Store **one** in secure storage and use it consistently.
6. Keep sending `Authorization: Bearer <token>`. Only the token's origin changes.
7. Generate and persist one UUID per install. Send it as `x-install-id` on sign-in requests.
8. On logout:
   1. `DELETE /v2/me/push-token` **first**, if push is registered. After sign-out it would return `401`.
   2. `POST /v2/auth/sign-out`.
   3. Clear local state.

**Web / browser**

5. Stop storing tokens in JavaScript. Let the browser hold the `HttpOnly` session cookie.
6. Send every request with `credentials: "include"`. Don't send an `Authorization` header.
7. Make sure the web origin is on the V2 CORS allowlist. Any `callbackURL` / `redirectTo` must be a trusted origin (V2 §A.8, F.3).

**Real-time**

9. Socket.IO `/live-agent`: put the **V2 session token** in the `authorization` handshake header (V2 §C.7).
10. Raw WebSockets: use the header or cookie, or a one-time `?ticket=` from `GET /v2/auth/one-time-token/generate`. `?token=` is rejected in production, and the V1 `auth_token` query param isn't read (V1 §9 · V2 §F.2).

---

## 2. Endpoint Migration Matrix

Change types: **Same** · **Changed** (same purpose and path pattern, different contract) · **Renamed** (new path, same purpose) · **Replaced** (different design) · **Removed** · **New in V2**.

### 2.1 Auth
| V1 Endpoint | V2 Endpoint | Method | Change Type | Migration Action | Notes |
|---|---|---|---|---|---|
| `/api/v1/auth/signup` | `/v2/auth/sign-up/email` | POST | Renamed | New path; `displayName`→`name`; password ≥ 12 | V1 §3 · V2 §A.3 |
| `/api/v1/auth/signin` | `/v2/auth/sign-in/email` | POST | Renamed | New path; new response; read `set-auth-token` | V1 §3 · V2 §A.3 |
| `/api/v1/auth/signin-oauth` | `/v2/auth/sign-in/social` | POST | Renamed | Wrap `idToken` + `nonce` in an object | Providers google / apple. LINE uses a redirect flow, **Needs manual review** · V2 §A.3 |
| `/api/v1/auth/refresh` | — | POST | Removed | Delete the refresh logic; sign in again on 401 | V2 §A.6 |
| `/api/v1/auth/signout` | `/v2/auth/sign-out` | POST | Renamed | New path; the session is revoked on the server | V2 §A.4 |
| `/api/v1/auth/send-otp` | `/v2/auth/email-otp/send-verification-otp` | POST | Changed | Add `type` (`sign-in`, `email-verification`, `forget-password`, `change-email`) | V1 §3 · V2 §C.1 |
| `/api/v1/auth/verify-otp` (`type: signup`) | `/v2/auth/email-otp/verify-email` | POST | Replaced | `token`→`otp`; drop `type` | V2 §A.3 |
| `/api/v1/auth/verify-otp` (`type: magiclink` / `email`) | `/v2/auth/sign-in/email-otp` | POST | Replaced | `token`→`otp`; drop `type` | V2 §A.3 |
| `/api/v1/auth/verify-otp` (`type: recovery`) | `/v2/auth/email-otp/check-verification-otp` (optional) + `/v2/auth/email-otp/reset-password` | POST | Replaced | Code check and password set merge into one reset call | V2 §C.1 |
| `/api/v1/auth/verify-otp` (`type: invite`, `email_change`) | — | POST | **Needs manual review** | No confirmed V2 equivalent for `invite`; `email_change` → see change-email | V1 §3 |
| `/api/v1/auth/resend-verification` | `/v2/auth/email-otp/send-verification-otp` (`type: "email-verification"`) | POST | Replaced | Same endpoint as send-otp, different `type` | V2 §A.3 |
| `/api/v1/auth/reset-password` | `/v2/auth/email-otp/request-password-reset` (code) or `/v2/auth/request-password-reset` (link) | POST | Renamed | Choose the code or link flow | V2 §C.1 |
| `/api/v1/auth/update-password` (after recovery) | `/v2/auth/email-otp/reset-password` or `/v2/auth/reset-password` | POST | Replaced | Reset with code + email, or with link token; no Bearer needed | V2 §C.1 |
| `/api/v1/auth/update-password` (signed in) | `/v2/auth/change-password` | POST | Replaced | Add `currentPassword` | V2 §C.1 |
| `/api/v1/auth/change-email/request` | `/v2/auth/change-email` | POST | Replaced | One call; no refresh token. Verified account: link to the **current** email. Unverified: changes immediately. Email already in use: still `{status:true}` | Step after the link click **Needs manual review** · V2 §C.1 |
| `/api/v1/auth/change-email/verify` | — | POST | Removed | Remove the code-entry screen | Folded into the link flow · V2 §C.1 |
| `/api/v1/auth/delete-account` | `/v2/account` | **DELETE** | Replaced | New method and path; send `password` (or require a fresh sign-in) | 30-day grace · V2 §C.3 |
| — | `/v2/auth/get-session` | GET | New in V2 | Use to read user + session (`glassUserId`, flags) | V2 §C.1, D.2 |
| — | `/v2/auth/sign-in/magic-link`, `/v2/auth/magic-link/verify` | POST / GET | New in V2 | Optional email-link sign-in via deep link | V2 §A.3 |
| — | `/v2/auth/one-time-token/generate` | GET | New in V2 | Needed for ticket-based WebSocket auth | V2 §F.2 |

### 2.2 Profile, account, app
| V1 Endpoint | V2 Endpoint | Method | Change Type | Migration Action | Notes |
|---|---|---|---|---|---|
| `/api/v1/user` | `/v2/me` | GET | Changed | Object instead of array; `id` is a UUID | V1 profile fields (phone, birthday, height, weight, gender, img, bg_image, language) **Needs manual review**: not in `/v2/me` or the documented `get-session` user · V1 §4 · V2 §C.2, D.2 |
| — | `/v2/me/push-token` | PUT / DELETE | New in V2 | Register after sign-in; remove **before** sign-out | V2 §C.2 |
| — | `/v2/me/device-removals` | GET | New in V2 | Poll on foreground to detect staff-removed glasses | V2 §C.2 |
| `/api/v1/app-version/check` | `/v2/app-releases/check` | GET | Changed | Send `build` + `osVersion` instead of `version`; read `status` | V1 §5 · V2 §C.4 |

### 2.3 Firmware
| V1 Endpoint | V2 Endpoint | Method | Change Type | Migration Action | Notes |
|---|---|---|---|---|---|
| `/api/v1/firmware/latest/{deviceType}` | `/v2/devices/{id}/firmware/check` | GET | Replaced | Key by owned device UUID, not device type; `currentVersion` required | V1 §6 · V2 §C.6 |
| `/api/v1/firmware/download/{firmwareId}` | — | GET | Removed | Use `release.url` from check (valid 15 min) | V2 §C.6 |
| `/api/v1/firmware/update-log` | `/v2/devices/{id}/firmware/updates` | POST | Replaced | Send **one** report at the end instead of create-at-start | V2 §C.6 |
| `/api/v1/firmware/update-log/{id}` | — | PATCH | Removed | Merged into the single report | V2 §C.6 |

### 2.4 Device binding
| V1 Endpoint | V2 Endpoint | Method | Change Type | Migration Action | Notes |
|---|---|---|---|---|---|
| `/api/v1/terminals/verify` | `/v2/devices/lookup` | POST | Replaced | `{macAddress}` only; no `cloud_token` | V1 §7 · V2 §C.5 |
| `/api/v1/terminals/bind` | `/v2/devices/bind` | POST | Replaced | camelCase body; drop `cloud_token`, `Idempotency-Key`, `claim` | V2 §C.5 |
| `/api/v1/terminals/{id}/unbind` | `/v2/devices/{id}/unbind` | POST | Changed | `{reason}`→optional `{cause}`; drop `Idempotency-Key`; UUID id | V2 §C.5 |
| `/api/v1/terminals/{id}/name` | `/v2/devices/{id}/rename` | POST | Renamed | Path `/name`→`/rename`; UUID id; max length 64→255 | V2 §C.5 |
| `/api/v1/me/terminals` | `/v2/devices` | GET | Renamed | Paginate with `limit` / `cursor`; key `terminals`→`devices` | V2 §C.5 |
| — | `/v2/devices/{id}` | GET | New in V2 | Fetch one owned device | V2 §C.5 |

### 2.5 Real-time
| V1 Endpoint | V2 Endpoint | Method | Change Type | Migration Action | Notes |
|---|---|---|---|---|---|
| Socket.IO `/live-agent` | Socket.IO `/live-agent` | WS | Changed | V2 token in header; event and param changes (§3.6, §4.6) | V1 §8 · V2 §C.7 |
| — | `wss://<host>/v2/assistant/live` | WS | New in V2 | Optional JSON alternative to Socket.IO | V2 §C.8 |
| `wss://<translation-host>/ws/translate_v2` | `wss://<api-host>/v2/translation/live` | WS | Replaced | New host, auth, frame format and audio format | V1 §9 · V2 §C.9 |

---

## 3. Request Migration

### 3.1 Auth
| Endpoint | V1 request | V2 request | Added | Removed | Renamed | Headers |
|---|---|---|---|---|---|---|
| Sign-up | `{email, password, displayName, phone?}` | `{email, password, name}` | — | `phone` | `displayName`→`name` | — |
| Sign-in | `{email, password}` | `{email, password, rememberMe?}` | `rememberMe` (optional) | — | — | add `x-install-id` |
| Social | `{provider, idToken: "<jwt>", nonce?}` | `{provider, idToken: {token, nonce?, accessToken?}}` | `idToken.accessToken` (optional) | — | `idToken`→`idToken.token`; `nonce`→`idToken.nonce` | add `x-install-id` |
| Refresh | `{code}` | — | — | whole call | — | — |
| Sign-out | (none) | (none) | — | — | — | V2 token in `Authorization` / cookie |
| Send code | `{email}` | `{email, type}` | `type` (required) | — | — | — |
| Verify sign-up code | `{email, token, type:"signup"}` | `{email, otp}` | — | `type` | `token`→`otp` | — |
| Code sign-in | `{email, token, type:"magiclink"\|"email"}` | `{email, otp}` | — | `type` | `token`→`otp` | add `x-install-id` |
| Request reset | `{email}` | code: `{email}` · link: `{email, redirectTo?}` | `redirectTo` (link flow) | — | — | — |
| Reset with code | V1: `verify-otp {email, token, type:"recovery"}` then `update-password {password, refresh_token?}` + Bearer | `{email, otp, password}` | — | `type`, `refresh_token`, Bearer | `token`→`otp` | no auth header needed |
| Change password | `{password, refresh_token?}` + Bearer | `{currentPassword, newPassword, revokeOtherSessions?}` | `currentPassword`, `revokeOtherSessions` | `refresh_token` | `password`→`newPassword` | — |
| Change email | `{newEmail, refreshToken}`, then `{token}` | `{newEmail, callbackURL?}` | `callbackURL` | `refreshToken`; second call | — | — |
| Delete account | `POST` (no body used) | `DELETE` `{password?}` | `password` | — | — | method POST→DELETE |

### 3.2 Profile and app version
| Endpoint | V1 request | V2 request | Added | Removed | Renamed | Headers |
|---|---|---|---|---|---|---|
| Current user | `GET /user` | `GET /v2/me` | — | — | — | — |
| App version | `?platform&version` | `?platform&build&osVersion` | `build` (integer), `osVersion` | `version` | — | — |

### 3.3 Firmware
| Endpoint | V1 request | V2 request | Added | Removed | Renamed |
|---|---|---|---|---|---|
| Check | `GET latest/{deviceType}?currentVersion` (optional) | `GET devices/{id}/firmware/check?currentVersion` (required) | device `id` (UUID) in path | `deviceType` path | — |
| Report | V1: `POST update-log {macId?, oldFirmwareVersion?, newFirmwareVersion?, startTime?}`, then `PATCH update-log/{id} {endTime, status, failureReason?}` | `POST devices/{id}/firmware/updates {releaseId, status, error?, sdkVersion, startedAt, endedAt}` | `releaseId` (from check), `sdkVersion` | `macId`, `oldFirmwareVersion`, `newFirmwareVersion` | `startTime`→`startedAt`; `endTime`→`endedAt`; `failureReason`→`error` |

`status` values are the same in both: `success | failed | cancelled | interrupted` (V1 §6 · V2 §C.6).

### 3.4 Device binding
| Endpoint | V1 request | V2 request | Added | Removed | Renamed | Headers |
|---|---|---|---|---|---|---|
| Verify → Lookup | `{mac_ble, model, observed_device_token?, firmware_ver?, reset_nonce?}` | `{macAddress}` | — | `model`, `observed_device_token`, `firmware_ver`, `reset_nonce` | `mac_ble`→`macAddress` | — |
| Bind | `{mac_ble, mac_bt, model, name, cloud_token, device_token, firmware_ver?, serial?, device_type?, frame_version?, os?, request_configuration_sn?, claim?}` | `{macAddress, macAddressBt?, modelCode?, name?, deviceToken?, firmwareVersion?, serialNumber?, frameVersion?, os?}` | — | `cloud_token`, `claim`, `device_type`, `request_configuration_sn` | `mac_ble`→`macAddress`; `mac_bt`→`macAddressBt`; `model`→`modelCode`; `device_token`→`deviceToken`; `firmware_ver`→`firmwareVersion`; `serial`→`serialNumber`; `frame_version`→`frameVersion` | **remove** `Idempotency-Key` |
| Unbind | `{reason}` (required, free text) | `{cause?}` (`user_unbind` \| `factory_reset`) | `cause` | `reason` | — | **remove** `Idempotency-Key` |
| Rename | `{name}` (1–64) | `{name}` (1–255) | — | — | — | — |
| List | `GET /me/terminals` | `GET /v2/devices?limit&cursor` | `limit`, `cursor` | — | — | — |

Request mapping notes:
- **Optionality:** V1 bind required `mac_bt`, `model`, `name` and `device_token`. In V2 everything except `macAddress` is optional.
- **Body strictness:** V1 bind / unbind / rename rejected unknown fields. V2 only validates the fields it knows (V1 §7 · V2 §C.5).
- **Needs manual review: `device_type`, `request_configuration_sn`.** They have no V2 bind field. Decide whether the device model is resolved from `modelCode` alone.

### 3.5 Live translation
| Item | V1 | V2 | Change |
|---|---|---|---|
| URL | `wss://<translation-host>/ws/translate_v2` | `wss://<api-host>/v2/translation/live` | host + path |
| Auth | `?auth_token=` | Header / cookie / `?ticket=` | removed `auth_token` |
| Query | `source_lang`, `target_lang` (required) | `source_lang` (default `auto`), `target_lang` (default `en`), `speak`, `timezone`, `device_mac` | added `speak`, `timezone`, `device_mac` |
| Audio up | **Binary** frames, PCM **Float32** LE, 16 kHz mono | **JSON** `{type:"audio", data:<base64 PCM16 16 kHz mono>}` | format and encoding |
| Heartbeat | Client sends `{"type":"ping"}` every 25 s; replies `pong` to server `ping` | Server sends `ping` every 20 s; client replies `{type:"pong"}`; closed after 90 s silent | direction changed |
| New client frames | — | `audio_end`, `speak`, `playback`, `disconnect` | added |

### 3.6 Live agent (Socket.IO)
| Item | V1 | V2 | Change |
|---|---|---|---|
| Auth header | `Authorization: Bearer <JWT>` | `authorization: Bearer <V2 session token>` | token type |
| Query `language` | sent | not read; use `app_language` | **renamed** |
| Query `device_mac` / `macId` | `macId` (optional) | `device_mac` | **renamed** |
| Query `device_type`, `firmware_version`, `timezone`, `city`, `country`, `current_date`, `current_time` | sent | read | same |
| Query `sessionType` | read | not read | removed |
| Query `platform`, `resume_key` | — | read | added |
| `audio_stream` | base64 string | base64 string (PCM16 16 kHz) | same |
| `message` | text | string or `{text, city?, country?}` | extended |
| `analyze_image` | `{image, message}` sent after the photo tool call | `photo_tool_response` `{status:"ok", data:{image}}` after the same `device_tool_call` (tools `thinkar_device_tool_page_take_AI_photo` / `…_take_photo`); QR: `qr_scan_tool_response` | Replaced. The ack payload for the photo tool **Needs manual review** |
| `video_stream` | handled | not handled | removed |
| `stop_agent` | handled | not handled; use `close_session` | removed |
| `close_session` | — | hang up | new |

---

## 4. Response Migration

### 4.1 Sign-in
| | V1 (`/auth/signin`) | V2 (`/v2/auth/sign-in/email`) |
|---|---|---|
| Shape | `{user:{session:{accessToken, refreshToken, expiresIn, expiresAt, token_type, email, user_id, user_role}, profile:{id, auth_id, name, …}, subscription}}` | `{redirect, token, user}` (+ `url` only when `callbackURL` is sent) + header `set-auth-token` (a different string from `token`; both valid) |

- **Removed:**
  - `refreshToken`, `expiresIn`, `expiresAt`, `token_type`
  - `profile` (use `GET /v2/me` or `GET /v2/auth/get-session`)
  - `subscription`: **Needs manual review**, no V2 equivalent in the inventory
  - `user_role` (V2 `user.role` is staff-only)
- **Renamed:**
  - `accessToken` → `token`
  - `user_id` → `user.id`
- **Type change:** the V1 `profile.id` integer is now `user.glassUserId` (from `get-session`). The UUID is `user.id`.

### 4.2 Social / code sign-in / refresh
| Endpoint | V1 | V2 | Changes |
|---|---|---|---|
| Social | Top level `{access_token, refresh_token, expires_in, expires_at, token_type, user}` | `{redirect:false, token, user}` + `set-auth-token` | `access_token`→`token`; removed `refresh_token`, `expires_*`, `token_type` |
| Code verify / sign-in | `{message, access_token, refresh_token, expires_in, expires_at, token_type, user}` | sign-up verify `{status, token, user}`; code sign-in `{token, user}` | `access_token`→`token`; removed `message`, `refresh_token`, `expires_*` |
| Refresh | `{user, session:{access_token, refresh_token, …}}` | — | removed |
| Sign-up | `{user:{message, email}}` | `{token: null, user}` | `token: null` is expected until the email is verified; `user` is the new user object |

### 4.3 Profile, account, app version
| Endpoint | V1 | V2 | Changes |
|---|---|---|---|
| Current user | `[ {id:int, auth_id, name, email, phone, language, birthday, height, weight, gender, img, bg_image, active, created_at} ]` | `{id:uuid, email, name}` | array → object; `auth_id`→`id`; integer `id` → `glassUserId` (in `get-session`); other profile fields **Needs manual review** |
| Delete account | `{message, data}` | `{success:true}` | — |
| App version | `{platform, latestVersion, minSupportedVersion, forceUpdate, hasUpdate, updateMessage, storeUrl, releaseNote}` | `{status, release:{version, buildNumber, notes, mandatory}\|null, storeUrl\|null}` | `forceUpdate`/`hasUpdate`→`status`; `latestVersion`→`release.version`; `releaseNote`→`release.notes`; `updateMessage`, `minSupportedVersion`, `platform` removed; added `buildNumber`, `mandatory`; `storeUrl` may be `null` |

### 4.4 Firmware
| Endpoint | V1 | V2 | Changes |
|---|---|---|---|
| Check | `{hasUpdate, isMandatory?, message, firmware?:{id:int, version, device_type, releasenotes, sha256, is_mandatory, created_at}}` | `{status, release:{id:uuid, version, notes, mandatory, url, sha256, sizeBytes}\|null, rules\|null}` | `hasUpdate`→`status`; `firmware`→`release`; `releasenotes`→`notes`; `is_mandatory`/`isMandatory`→`release.mandatory`; `id` int→UUID; added `url`, `sizeBytes`, `rules`; removed `message`, `device_type`, `created_at` |
| Download | `{download_url}` | — | now `release.url` |
| Report | create `{id:int}`; patch `{id:int}` | `{id:uuid}` | int → UUID |

### 4.5 Device binding
**Device object** (V1 `terminal` → V2 Device):

| V1 field | V2 field | Change |
|---|---|---|
| `id` (int) | `id` (UUID) | type |
| `mac_ble` | `macAddress` | renamed |
| `mac_bt` | `macAddressBt` | renamed |
| `model` | `modelCode` (+ new `modelId`) | renamed |
| `name` | `name` | same |
| `firmware_ver` | `firmwareVersion` | renamed |
| `serial` | `serialNumber` | renamed |
| `bound_at` | `boundAt` | renamed |
| `status` (`active\|unbound\|force_released\|archived\|disputed_revoked`) | `status` (`provisioned\|retired\|blocked`) | **meaning changed**: binding state → registry state |
| `device_token` | `deviceToken` | renamed |
| — | `os`, `frameVersion`, `lastSeenAt` | added |

**Endpoint responses:**

| Endpoint | V1 | V2 | Changes |
|---|---|---|---|
| Verify → Lookup | `{state, cloud_token, cloud_token_ble, expires_at, ttl_seconds, device_token?, claim_after_reset_allowed?, terminal}` | `{state, device\|null}` | `terminal`→`device` (registry view, never owner or token); removed `cloud_token*`, `expires_at`, `ttl_seconds`, `device_token`, `claim_after_reset_allowed` |
| Bind | `{terminal}` | Device (no wrapper) | unwrapped |
| Unbind | `{terminal}` or `{}` | `{released: boolean}` | replaced |
| Rename | `{terminal}` | Device (no wrapper) | unwrapped |
| List | `{terminals:[…]}` | `{devices:[…], nextCursor}` | renamed + pagination |

**Lookup `state` values:**

| V1 | V2 | Notes |
|---|---|---|
| `available` | `claimable` | |
| `owned_by_you` | `owned_by_me` | |
| `owned_by_other` | `owned_by_other` | same |
| — | `unregistered` | V1 returned 404 `DEVICE_NOT_PROVISIONED` instead |
| — | `blocked`, `retired` | V1 returned 409 `DEVICE_UNAVAILABLE` instead |
| `release_directive` | — | **Needs manual review**: no V2 equivalent |
| `reserved_by_other` | — | **Needs manual review**: no V2 equivalent |

- **`cloud_token_ble`** (the integer for the glasses handshake) has no V2 source. **Needs manual review:** confirm how the glasses handshake works without it (V1 §7 · V2 §C.5).
- **`deviceToken` source.** In V1 it came from `verify` (`owned_by_you`) and `bind`. In V2 it comes only from `bind` / `get` / `list` / `rename`, never from `lookup` (V2 §C.5, D.3).

### 4.6 Real-time responses
**Live agent (Socket.IO server → client):**

| V1 event | V2 event | Change |
|---|---|---|
| `gemini_session_opened` | `gemini_session_opened {resume_key}` | payload added |
| `gemini_audio` | `gemini_audio {data}` | same name |
| `gemini_input_transcript`, `gemini_output_transcript` | same | input gains `is_final:false` |
| `gemini_turn_complete`, `gemini_interrupted` | same | same |
| `device_tool_call` + ack | same, ack within **30 s** | timeout added |
| `gemini_error` / `error` | `error {message, code?, retryAfterMs?}` | use `error` only |
| `gemini_response`, `gemini_text_response`, `gemini_request_lost`, `dual_session_error`, session-lifecycle events (`session_refreshing`, `gemini_reconnecting`, …), `agent_stopped`, `tool_call_started/ended` | — | removed |
| — | `session_revoked` | new |

**Live translation (server → client):**

| V1 | V2 | Change |
|---|---|---|
| JSON `{source_text, translation\|text, complete}` | `partial {sentenceId, text, sourceText}` / `final {sentenceId, text, sourceText, detectedLanguage?}` | `source_text`→`sourceText`; `translation`→`text`; `complete:false/true`→`type: partial/final`; added `sentenceId`, `detectedLanguage` |
| Binary TTS frames | JSON `audio {sentenceId, data:<base64 PCM16 24 kHz>}` bracketed by `playing_started` / `playing_finished` | binary → JSON |
| — | `connected {sessionId}`, `error {message, code?, retryAfterMs?}` | new |

---

## 5. Error Handling Migration

### 5.1 Error structure
| V1 | V2 |
|---|---|
| Standard: `{statusCode, message, error}` | **One envelope for everything:** `{error:{code, status, message, details?}}` |
| Validation (two formats): auth/user `{statusCode:400, message:"Validation failed", errors:[{path:[…], message, …}]}`; device/firmware `{message:"Validation failed", errors:[{path:"<field>", message, metadata}]}` | Validation: `400 {error:{code:"VALIDATION_FAILED", details:[{field, code}]}}` on `/v2` resource endpoints; **no `details`** on `/v2/auth/*` |
| Terminal: `{code, message}` | Device errors use the same envelope with `DEVICE_*` codes |

References: V1 §10 · V2 §E.1.

**Action:** replace all V1 parsers with one that reads `error.code`. `message` is for debugging only (V2 §E.1).

### 5.2 Authentication errors
| Situation | V1 | V2 |
|---|---|---|
| No / invalid token | 401 `Unauthorized` / `No authorization header provided` | 401 `UNAUTHENTICATED` |
| Wrong credentials | 401 (text) | 401 `AUTH_INVALID_CREDENTIALS` |
| Email not confirmed | 403 (text) | 403 `AUTH_EMAIL_NOT_VERIFIED` |
| Inactive / banned | 403 (text) | 403 `AUTH_ACCOUNT_BANNED` |
| Invalid / expired code | 401 (text) | **400** `AUTH_INVALID_OTP` |
| Invalid refresh token | 401 | n/a (no refresh) |
| Email already registered | 409 | 409 `AUTH_USER_ALREADY_EXISTS` |
| Account removed by staff | — | 401 `ACCOUNT_DELETED_BY_ADMIN` |
| Must change password | — | 403 `AUTH_MUST_CHANGE_PASSWORD` |
| Re-auth needed | — | 403 `AUTH_REAUTH_REQUIRED` |
| Too many requests | — | 429 `RATE_LIMITED` + `retry-after` |

References: V1 §3 · V2 §E.2–E.3.

**Status change to note:** an invalid code was 401 in V1 and is 400 in V2. A client that treats every 401 as "session lost" must not apply that logic to code entry, and must not miss the 400.

### 5.3 Validation errors
| Item | V1 | V2 |
|---|---|---|
| Status | 400 | 400 (`VALIDATION_FAILED`). `DEVICE_TOKEN_INVALID` stays **422** |
| Field info | `errors[].path` (array or string), `errors[].message` | `details[].field`, `details[].code` (no message, no submitted value); not present on `/v2/auth/*` errors |
| Password too short/long | 400 (validation) | 400 `VALIDATION_FAILED` (12–128 chars) |

### 5.4 Permission and ownership errors
| Situation | V1 | V2 |
|---|---|---|
| Role required | 403 `Insufficient permissions` | 403 `FORBIDDEN` (staff routes only; customer routes have no roles) |
| Not the device owner | 403 `FORBIDDEN` | 403 `DEVICE_NOT_OWNED` |
| Unknown device id (unbind) | 404 `NOT_FOUND` | **200** `{released:false}`: treated as already released |
| Unknown device id (rename) | 404 `NOT_FOUND` | **403** `DEVICE_NOT_OWNED` (rename doesn't distinguish unknown from not-owned) |
| Unknown device id (get / firmware) | — | 404 `DEVICE_NOT_FOUND` |

### 5.5 Device-binding codes
| V1 code (HTTP) | V2 code (HTTP) | Notes |
|---|---|---|
| `DEVICE_NOT_PROVISIONED` (404) | `DEVICE_NOT_PROVISIONED` (404) | same |
| `OWNED_BY_OTHER` (409) | `DEVICE_ALREADY_OWNED` (409) | renamed |
| `DEVICE_UNAVAILABLE` (409) | `DEVICE_BLOCKED` (409), or `DEVICE_NOT_PROVISIONED` (404) for a retired device | split |
| `DEVICE_TOKEN_INVALID` (422) | `DEVICE_TOKEN_INVALID` (422) | same |
| `CLOUD_TOKEN_EXPIRED` (410), `INVALID_CLOUD_TOKEN` (400) | — | removed with `cloud_token` |
| `MISSING_IDEMPOTENCY_KEY` (400), `IDEMPOTENCY_MISMATCH` (422) | — | removed |
| `CLAIM_RATE_LIMITED` (429), `INVALID_CLAIM_TOKEN` (400) | — | removed with `claim` |
| `RESERVED_BY_OTHER` (409) | — | **Needs manual review** |
| `UNSUPPORTED_MODEL` (400) | — | **Needs manual review**: V2 lookup/bind show no model check; firmware check returns `unknown-model` |
| — | `DEVICE_CONTENDED` (409) | new: retry |

### 5.6 App version and firmware
| Situation | V1 | V2 |
|---|---|---|
| No version config | 404 (treated as "no update") | not possible; always 200 + `status` |
| Firmware not found / no update | 200 `{hasUpdate:false}` or 404 | 200 `{status:"up-to-date"}`; 404 only for an unknown device |
| Storage problem | — | 503 |

### 5.7 Real-time errors
| Channel | V1 | V2 |
|---|---|---|
| Live agent auth failure | Socket disconnected, no error event | `connect_error` with reason |
| Live agent runtime error | `gemini_error` / `error` | `error {message, code?, retryAfterMs?}` |
| Translation | Not specified in V1 §9 | `{type:"error", code?}` + close codes 4401 / 4500 / 4503 |

---

## 6. Client Migration

### 6.1 Web applications
- **Auth**
  - Remove token storage and the `Authorization` header.
  - Use the `HttpOnly` session cookie. Send every request with `credentials: "include"`.
  - Get the web origin added to the V2 CORS allowlist. Requests from unlisted origins get no credentialed CORS response (V2 §F.3).
  - Pass only trusted URLs as `callbackURL` / `redirectTo`.
- **Session**
  - Remove refresh timers.
  - On `401`, redirect to sign-in.
  - On `403 AUTH_MUST_CHANGE_PASSWORD`, route to change-password.
- **Real-time:** browsers can't set WebSocket headers. Use the cookie, or get a ticket from `GET /v2/auth/one-time-token/generate` and connect with `?ticket=` (V2 §F.2).
- **Calls and errors:** update all paths and payloads (§2–§4) and parse the V2 error envelope.

### 6.2 Mobile applications
- **Auth**
  - Replace JWT + refresh token storage with **one session token** from `set-auth-token`, kept in secure storage.
  - Keep the `Authorization: Bearer` header.
  - Delete the refresh logic. On `401`, return to sign-in.
- **New headers:** send `x-install-id` (persisted UUID) on sign-in. Optionally send `x-timezone` and the `x-client-*` headers.
- **Lifecycle**
  - Register push with `PUT /v2/me/push-token`. Remove it **before** calling sign-out.
  - Check `GET /v2/me/device-removals` on foreground.
- **Binding**
  - Replace verify → cloud token → bind with lookup → bind. Remove `Idempotency-Key` handling and the factory-reset claim flow.
  - Store device ids as UUID strings.
  - Read `deviceToken` from bind / list / get.
  - **Needs manual review:** how the glasses handshake works without `cloud_token` / `cloud_token_ble` (§4.5).
- **Firmware**
  - Check per device.
  - Download from `release.url` within 15 minutes.
  - Report once with `releaseId` + `sdkVersion`. Replace the V1 create/patch retry queue.
- **App version:** send `build` (integer build number) + `osVersion`; branch on `status`.
- **Live agent:** V2 token in the handshake header; `language`→`app_language`; `macId`→`device_mac`; remove `analyze_image` / `video_stream` / `stop_agent`; handle `error` and `session_revoked`; ack tool calls within 30 s.
- **Live translation:** move to the API host; header auth; JSON frames; base64 **PCM16** instead of binary Float32; reply to server `ping`; parse `partial` / `final` / `audio`; handle close codes.
- **Identity:** use `glassUserId` (integer) where the V1 profile `id` was used for the glasses (V2 §D.2).

### 6.3 API clients (server-to-server, scripts, SDKs)
- Base URL: `/api/v1` → `/v2`.
- Auth: sign in via `/v2/auth/sign-in/email`, keep the token from `set-auth-token`, send it as `Authorization: Bearer`. There's no refresh; sign in again when you get `401`.
- Don't use the JWT from `/v2/auth/token` for `/v2` calls; it isn't accepted.
- Use `GET /openapi.json` for the full schema (V2 §B).
- Parse `error.code`. Respect `429` + `retry-after`.

---

## 7. Breaking Changes

Each of these breaks an unmodified V1 client:

1. **Base path** changed (`/api/v1` → `/v2`). Every V1 URL returns 404.
2. **V1 tokens rejected.** Users must sign in again.
3. **Refresh endpoint removed.** The refresh flow fails.
4. **Sign-in response changed.** `user.session.accessToken`, `refreshToken`, `expiresAt` and `profile` are gone.
5. **Social sign-in body changed.** `idToken` must be an object.
6. **Password minimum raised** from 8 to 12. Shorter passwords are rejected on sign-up, reset and change.
7. **Sign-up field** `displayName` → `name`.
8. **Single `verify-otp` replaced** by separate code endpoints. `token` → `otp`.
9. **Change password needs `currentPassword`.**
10. **Change email is link-based.** The code-verify endpoint is gone.
11. **Delete account** is now `DELETE /v2/account` and needs re-authentication.
12. **`GET /user` → `GET /v2/me`.** Array → object, integer id → UUID, profile fields reduced.
13. **App version check** needs `build` + `osVersion`. The response is a `status` enum, and there's no 404.
14. **Firmware:** check is per device UUID, the download endpoint is removed, and the update log is a single report.
15. **Device binding:** `terminals` → `devices`; no `cloud_token`, `Idempotency-Key` or `claim`; camelCase fields; UUID ids; `/name` → `/rename`; wrapped responses unwrapped; paginated list.
16. **Device `status` meaning changed** (binding state → registry state).
17. **Error format changed** for every endpoint.
18. **Code-entry errors** went from 401 to 400.
19. **Unknown device id** went from 404 to `200 {released:false}` on unbind, and from 404 to 403 on rename.
20. **Live agent:** token type, renamed params, removed events (`analyze_image`, `video_stream`, `stop_agent`, `gemini_error`).
21. **Live translation:** new host, auth, frame format (JSON), audio encoding (PCM16 base64, not binary Float32), result field names, heartbeat direction.
22. **Server-side session ending:** a newer phone sign-in, password reset or account deletion invalidates the session immediately.

---

## 8. Migration Checklist

**Preparation**
- [ ] Get the V2 host(s) for each environment, plus the cookie domain, deep-link scheme and CORS allowlist status (V2 §H).
- [ ] Resolve every **Needs manual review** item (list below).
- [ ] Download `GET /openapi.json` from the target environment.

**Configuration**
- [ ] Point REST calls at `https://<host>/v2`.
- [ ] Point Socket.IO at `https://<host>` (namespace `/live-agent`).
- [ ] Point translation at `wss://<host>/v2/translation/live` and remove the separate translation host.

**Authentication**
- [ ] Remove V1 access/refresh token storage, the refresh call and refresh timers.
- [ ] Mobile/API: store the V2 session token from `set-auth-token` and send it as `Authorization: Bearer`.
- [ ] Web: remove the `Authorization` header and use cookies with `credentials: "include"`.
- [ ] Mobile: generate and persist `x-install-id`; send it on sign-in.
- [ ] Implement sign-in (email, social with the `idToken` object, email code), sign-up (`name`, 12-char passwords) and sign-up code verification.
- [ ] Implement password reset (code or link), change password (`currentPassword`) and change email (link).
- [ ] Implement sign-out: `DELETE /v2/me/push-token` **first**, then `POST /v2/auth/sign-out`, then clear local state.
- [ ] Sign-up: treat `token: null` as "verification pending".
- [ ] Implement account deletion: `DELETE /v2/account` with `password`, and handle `AUTH_REAUTH_REQUIRED` / `ACCOUNT_SOLE_OWNER`.
- [ ] On any `401`, go to sign-in. On `403 AUTH_MUST_CHANGE_PASSWORD`, go to change-password.

**User data**
- [ ] Replace `GET /user` with `GET /v2/me` / `GET /v2/auth/get-session`.
- [ ] Switch user ids to UUID strings. Use `glassUserId` for the glasses' user number.

**Devices**
- [ ] Replace verify/bind with `POST /v2/devices/lookup` + `POST /v2/devices/bind` (camelCase, no `cloud_token`, `Idempotency-Key` or `claim`).
- [ ] Update unbind (`cause`), rename (`/rename`) and list (`/v2/devices`, pagination).
- [ ] Switch device ids to UUID strings. Map device `status` to the new meaning.
- [ ] Read `deviceToken` from bind / list / get.

**Firmware and app version**
- [ ] Use `GET /v2/devices/{id}/firmware/check?currentVersion=`; download from `release.url` within 15 minutes.
- [ ] Send one `POST /v2/devices/{id}/firmware/updates` at the end. Remove the create/patch log flow.
- [ ] Use `GET /v2/app-releases/check?platform&build&osVersion` and render `status`.

**Real-time**
- [ ] Live agent: V2 token in the header, `app_language`, `device_mac`, `resume_key`; remove the dropped events; handle `error`, `session_revoked`; ack tool calls within 30 s.
- [ ] Live translation: header or ticket auth, JSON frames, base64 PCM16 16 kHz upload, `pong` replies, `partial` / `final` / `audio` handling, close codes 4401 / 4500 / 4503.

**Errors**
- [ ] Replace all error parsing with `error.code`, and map the codes in §5.
- [ ] Handle `429` with `retry-after`.

**Optional new features**
- [ ] Push token registration and `GET /v2/me/device-removals` polling.
- [ ] Magic-link sign-in via deep link.

**Verification**
- [ ] Test with a migrated V1 account: email/password, Google and Apple sign-in should work without a reset.
- [ ] Test with a glasses unit bound in V1: it should appear in `GET /v2/devices` with its `deviceToken` and reconnect.
- [ ] Test session ending: sign out, sign in on a second phone, password reset.
- [ ] Test every error path you depend on.

### Needs manual review
| # | Item | Why |
|---|---|---|
| 1 | V1 profile fields (`phone`, `birthday`, `height`, `weight`, `gender`, `img`, `bg_image`, `language`) | Not present in `/v2/me` or the documented `get-session` user |
| 2 | V1 sign-in `subscription` | No V2 equivalent in the inventory |
| 3 | `verify-otp` types `invite` and `email_change` | No confirmed V2 mapping |
| 4 | `cloud_token` / `cloud_token_ble` for the glasses handshake | Removed in V2; the replacement handshake source isn't documented |
| 5 | Lookup states `release_directive`, `reserved_by_other` and the `RESERVED_BY_OTHER` code | No V2 equivalent |
| 6 | Factory-reset takeover (`claim: true`) | No V2 path; owned-by-other bind is refused |
| 7 | Bind fields `device_type`, `request_configuration_sn`; error `UNSUPPORTED_MODEL` | No V2 field or code |
| 8 | Acknowledgement payload for the photo tool call (`photo_tool_response` replaces `analyze_image`) | Event mapping confirmed; exact ack payload not traced |
| 9 | LINE sign-in | Uses a redirect flow, not the ID-token call |
| 10 | Step after the change-email confirmation link is clicked | Not traced |

**Resolved since the first analysis:**
- V2 sign-up body is `{token: null, user}`.
- V2 email-code sign-in creates the account if none exists.
- Every V2 account has a `glassUserId`.
