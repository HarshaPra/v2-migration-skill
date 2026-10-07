# API V1 → V2 Migration Guide

## 1. Introduction

This guide explains how to move an existing application from **API V1** to **API V2**. It covers:

- authentication and sessions
- every V1 endpoint and its V2 replacement
- request and response changes, with before/after examples
- the new error format
- what to change in web apps, mobile apps and other API clients
- the real-time channels (AI assistant and live translation)

V2 is not backward compatible with V1. Paths, tokens, payloads and errors all change. Plan the migration as a release of your app, not a configuration switch.

**Who should read this:** developers who maintain an app or service that calls API V1 today.

---

## 2. Before You Start

### 2.1 Requirements
| You need | Notes |
|---|---|
| The V2 host for each environment (dev, staging, production) | REST, WebSockets and Socket.IO share one host |
| A test account that existed in V1 | To check that existing users can sign in |
| A pair of glasses bound to that account in V1 | To check that existing bindings carry over |
| Access to the V2 API reference | `GET https://<host>/openapi.json`, or `https://<host>/docs` |
| Your web origin on the V2 allowlist (web apps only) | Ask the API team |
| Your app's deep-link scheme registered (only if you use magic-link sign-in) | Ask the API team |

### 2.2 What you need to know
- **Existing accounts are available in V2.** Users keep their email/password and Google/Apple sign-in, and don't need to reset their password. Exceptions:

  | V1 account | In V2 |
  |---|---|
  | Had an **expired temporary password** | Must use password reset |
  | Email was **never verified** | Sign-in returns `AUTH_EMAIL_NOT_VERIFIED`; the user must verify first |
  | Was **inactive or banned** | Sign-in returns `AUTH_ACCOUNT_BANNED` |
  | Deleted, anonymous, had no email or no way to sign in, or a **second account with the same email** | Not available; the user must sign up |

- **Existing sessions do not carry over.** V1 tokens aren't accepted by V2, so every user signs in once after your update.
- **Existing glasses bindings are available in V2.** Bound glasses keep their owner and device token, so they reconnect without pairing again. Exceptions:

  | V1 device | In V2 |
  |---|---|
  | Owner wasn't a valid account, or the device wasn't in an owned state | Unowned; the user binds it again |
  | Device token wasn't a 1–20 digit number | Kept without a token; the user binds again to store one |
  | Deleted or decommissioned | `retired`; it can't be bound |
- **There is no refresh token in V2.** Sessions last 7 days and renew automatically while in use.
- **Mobile apps keep the Bearer header.** Only browsers move to cookies.
- **Everything is on one host.** Live translation no longer uses a separate server.

### 2.3 Items still being confirmed
The following V1 features have no confirmed V2 equivalent yet. If your app depends on one of them, contact the API team before migrating:

| V1 feature | Status |
|---|---|
| Extra profile fields: `phone`, `birthday`, `height`, `weight`, `gender`, `img`, `bg_image`, `language` | Not returned by the V2 user endpoints |
| `subscription` object in the sign-in response | No V2 equivalent documented |
| Email-code types `invite` and `email_change` | No V2 equivalent documented |
| Glasses handshake values `cloud_token` / `cloud_token_ble` from `terminals/verify` | Not part of V2 |
| Binding states `release_directive`, `reserved_by_other` | Not part of V2 |
| Claiming a factory-reset device bound to another account (`claim: true`) | Not available in V2 |
| Bind fields `device_type`, `request_configuration_sn`; error `UNSUPPORTED_MODEL` | Not part of V2 |
| Live agent `analyze_image` event | Replaced by `photo_tool_response` (§6.9). The exact acknowledgement payload for the photo tool call is still being confirmed |
| LINE sign-in | Uses a browser redirect flow, not the ID-token call in §4.3; details still being confirmed |
| What happens after the user clicks the change-email confirmation link (§6.6) | Still being confirmed |

---

## 3. What Changed

| Area | V1 | V2 |
|---|---|---|
| Base URL | `https://<host>/api/v1` | `https://<host>/v2` |
| Credential | JWT access token + refresh token | Session token (server-side session) |
| Browser auth | `Authorization` header | Session cookie |
| Mobile / API auth | `Authorization: Bearer <JWT>` | `Authorization: Bearer <session token>` |
| Session length | Short-lived JWT, refreshed by the client | 7 days, renewed automatically with use |
| Token refresh | `POST /auth/refresh` | None |
| Logout | Client discards the token | Server ends the session immediately |
| Sessions per user | Unlimited | One phone per account (when the app sends `x-install-id`) |
| Field naming | Mixed (camelCase and snake_case) | camelCase in REST bodies |
| Ids | Integers (users, devices, firmware) | UUID strings (users still have a numeric `glassUserId`) |
| Errors | Several formats | One format: `{ "error": { "code", "status", "message", "details" } }` |
| Device binding | `terminals/*` with `cloud_token` and `Idempotency-Key` | `devices/*`, no cloud token, no idempotency header |
| Firmware | By device type; separate download call; log created then updated | By device; download link in the check; one report at the end |
| App update check | `version` string; `forceUpdate` / `hasUpdate` flags | `build` number + `osVersion`; one `status` value |
| Live agent | Socket.IO `/live-agent` | Socket.IO `/live-agent` (updated), or a new raw WebSocket |
| Live translation | Separate host, binary Float32 audio | API host `/v2/translation/live`, JSON frames, base64 PCM16 audio |
| Passwords | Minimum 8 characters | 12–128 characters |

---

## 4. Authentication Migration

### 4.1 V1
- `POST /api/v1/auth/signin` returned an **access token** (JWT), a **refresh token** and expiry times.
- The client sent `Authorization: Bearer <access token>` on every call.
- Before expiry, the client called `POST /api/v1/auth/refresh` with `{ "code": "<refresh token>" }` to get new tokens.
- Logout didn't end the token on the server; the client just deleted it.

### 4.2 V2
- Signing in creates a **session on the server** and returns a **session token**.
- How to present the session:

  | Client | Send |
  |---|---|
  | Mobile app / server / script | `Authorization: Bearer <session token>` |
  | Browser | The session cookie, set automatically by the sign-in response |

- Sessions last **7 days** and are extended automatically while in use. There is **no refresh token and no refresh call**.
- The server can end a session at any time (sign-out, password reset, account deletion, another phone signing in). The next request then returns `401`.
- V2 also has a JWT endpoint (`GET /v2/auth/token`), but **that JWT is not accepted** by `/v2` endpoints. Always use the session token.

### 4.3 Login migration

**Where the session token comes from.** Every V2 sign-in returns it twice:
- in the **`set-auth-token` response header**, and
- in the `token` field of the JSON body.

Mobile and API clients: store **one** of them and use it consistently. Both work as `Authorization: Bearer`, but they are **different strings**: the header carries a signed form of the token, the body carries the plain token. Don't compare them.

Browsers don't need to store anything: the cookie is set for them.

**Email and password**
```http
POST /v2/auth/sign-in/email
Content-Type: application/json
x-install-id: 3f1c2a9e-8b7d-4e6f-9a10-2b3c4d5e6f70

{ "email": "user@example.com", "password": "correct-horse-battery" }
```
```http
HTTP/1.1 200 OK
set-auth-token: <session token>

{ "redirect": false, "token": "<session token>", "user": { "id": "<uuid>", "email": "user@example.com", "name": "...", "emailVerified": true, "...": "..." } }
```
- `user` is abbreviated here.
- `url` appears only when you send a `callbackURL`.

**Google / Apple**
```http
POST /v2/auth/sign-in/social
Content-Type: application/json

{ "provider": "apple", "idToken": { "token": "<provider id token>", "nonce": "<raw nonce>" } }
```

**Email code sign-in**
1. `POST /v2/auth/email-otp/send-verification-otp` with `{ "email": "...", "type": "sign-in" }`
2. `POST /v2/auth/sign-in/email-otp` with `{ "email": "...", "otp": "123456" }` → `{ "token", "user" }`

If no account exists for the email, this call **creates one** (as V1 `send-otp` did).

**Magic link (optional)**
1. `POST /v2/auth/sign-in/magic-link` with `{ "email": "..." }`.
2. The email link opens `https://<host>/magic-link-open?token=…`, which redirects to `<your-scheme>://magic-link-verify?token=…`.
3. Your app calls `GET /v2/auth/magic-link/verify?token=…` → `{ "token", "user", "session" }`.

**Sign-up**
1. `POST /v2/auth/sign-up/email` with `{ "email", "password", "name" }`.
   - Response: `200 { "token": null, "user": { … } }`.
   - `token: null` is expected and is **not** an error: no session exists until the email is verified.
   - A 6-digit code is emailed.
2. `POST /v2/auth/email-otp/verify-email` with `{ "email", "otp" }` → `{ "status": true, "token", "user" }`. The user is now signed in.
3. To resend the code: `POST /v2/auth/email-otp/send-verification-otp` with `{ "email", "type": "email-verification" }`.

**`x-install-id` (mobile apps).** Generate one UUID when the app is installed, keep it, and send it as `x-install-id` on every sign-in request. When a user signs in on a new phone, V2 signs out their **older** phones. Without this header, that rule doesn't apply.

**Password rules.** Passwords must be **12 to 128 characters**. Update your sign-up, reset and change-password forms.

### 4.4 Authenticated requests

**Mobile and API clients**
```http
GET /v2/me
Authorization: Bearer <session token>
```

**Browsers**
```js
fetch("https://<host>/v2/me", { credentials: "include" });
```
Don't add an `Authorization` header in the browser.

**Optional headers (mobile)**

| Header | Purpose |
|---|---|
| `x-timezone` | IANA time zone, e.g. `Asia/Colombo` |
| `x-client-brand`, `x-client-model`, `x-client-os` | Phone details for the device history, max 64 characters each |

### 4.5 Logout migration
Do the steps **in this order**:

1. **Mobile apps registered for push:** remove the push token **while the session is still valid**:
   ```http
   DELETE /v2/me/push-token
   Authorization: Bearer <session token>

   { "token": "<expo push token>" }
   ```
2. Sign out:
   ```http
   POST /v2/auth/sign-out
   Authorization: Bearer <session token>
   ```
   ```json
   { "success": true }
   ```
3. Clear local state.

- Sign-out ends the session **on the server** immediately, and the token can't be reused.
- If you call `DELETE /v2/me/push-token` after sign-out, it returns `401` and the phone keeps receiving pushes for that account.

### 4.6 Session expiration

| | V1 | V2 |
|---|---|---|
| Lifetime | Short-lived JWT (`expiresIn` / `expiresAt` returned) | 7 days |
| Renewal | Client calls `/auth/refresh` before expiry | Automatic: extended once a day while used |
| What the client tracks | `expiresAt`, refresh token | Nothing |
| When it ends early | — | Sign-out, password reset, account deletion, a newer phone signing in, account removed by staff |

**What to do:**
1. Delete all refresh logic and expiry timers.
2. On **`401`**, send the user to the sign-in screen.
3. On **`403 AUTH_MUST_CHANGE_PASSWORD`**, send the user to change their password.
4. On **`403 AUTH_REAUTH_REQUIRED`**, ask the user to sign in again (or enter their password) before retrying.

---

## 5. API Endpoint Migration

Change types:

| Type | Meaning |
|---|---|
| **Renamed** | New path, same purpose |
| **Changed** | Same purpose, different contract |
| **Replaced** | Different design |
| **Removed** | No V2 equivalent |
| **New** | Only in V2 |

### 5.1 Authentication
| V1 | V2 | Method | Type | What to do |
|---|---|---|---|---|
| `/api/v1/auth/signup` | `/v2/auth/sign-up/email` | POST | Renamed | `displayName` → `name`; 12-char passwords |
| `/api/v1/auth/signin` | `/v2/auth/sign-in/email` | POST | Renamed | Read `set-auth-token`; new response |
| `/api/v1/auth/signin-oauth` | `/v2/auth/sign-in/social` | POST | Renamed | `idToken` becomes an object (Google, Apple) |
| `/api/v1/auth/refresh` | — | POST | Removed | Delete refresh logic |
| `/api/v1/auth/signout` | `/v2/auth/sign-out` | POST | Renamed | Session ends on the server |
| `/api/v1/auth/send-otp` | `/v2/auth/email-otp/send-verification-otp` | POST | Changed | Add `type` |
| `/api/v1/auth/verify-otp` (signup) | `/v2/auth/email-otp/verify-email` | POST | Replaced | `token` → `otp` |
| `/api/v1/auth/verify-otp` (magiclink / email) | `/v2/auth/sign-in/email-otp` | POST | Replaced | `token` → `otp` |
| `/api/v1/auth/verify-otp` (recovery) | `/v2/auth/email-otp/reset-password` | POST | Replaced | Code + new password in one call |
| `/api/v1/auth/resend-verification` | `/v2/auth/email-otp/send-verification-otp` | POST | Replaced | `type: "email-verification"` |
| `/api/v1/auth/reset-password` | `/v2/auth/email-otp/request-password-reset` (code) or `/v2/auth/request-password-reset` (link) | POST | Renamed | Pick code or link flow |
| `/api/v1/auth/update-password` (after recovery) | `/v2/auth/email-otp/reset-password` or `/v2/auth/reset-password` | POST | Replaced | No Bearer token needed |
| `/api/v1/auth/update-password` (signed in) | `/v2/auth/change-password` | POST | Replaced | Add `currentPassword` |
| `/api/v1/auth/change-email/request` | `/v2/auth/change-email` | POST | Replaced | Confirmed by email link |
| `/api/v1/auth/change-email/verify` | — | POST | Removed | Remove the code screen |
| `/api/v1/auth/delete-account` | `/v2/account` | **DELETE** | Replaced | Send `password`; 30-day grace |
| — | `/v2/auth/get-session` | GET | New | Read user and session |
| — | `/v2/auth/sign-in/magic-link`, `/v2/auth/magic-link/verify` | POST / GET | New | Optional email-link sign-in |
| — | `/v2/auth/email-otp/check-verification-otp` | POST | New | Optional code check before reset |
| — | `/v2/auth/one-time-token/generate` | GET | New | Ticket for WebSocket auth |

### 5.2 User, account, app
| V1 | V2 | Method | Type | What to do |
|---|---|---|---|---|
| `/api/v1/user` | `/v2/me` | GET | Changed | Object instead of array; UUID id |
| — | `/v2/me/push-token` | PUT / DELETE | New | Register / remove push token |
| — | `/v2/me/device-removals` | GET | New | Detect glasses removed by support |
| `/api/v1/app-version/check` | `/v2/app-releases/check` | GET | Changed | Send `build` + `osVersion`; read `status` |

### 5.3 Firmware
| V1 | V2 | Method | Type | What to do |
|---|---|---|---|---|
| `/api/v1/firmware/latest/{deviceType}` | `/v2/devices/{id}/firmware/check` | GET | Replaced | Use the device UUID |
| `/api/v1/firmware/download/{firmwareId}` | — | GET | Removed | Use `release.url` from the check |
| `/api/v1/firmware/update-log` | `/v2/devices/{id}/firmware/updates` | POST | Replaced | One report at the end |
| `/api/v1/firmware/update-log/{id}` | — | PATCH | Removed | Merged into the report |

### 5.4 Devices
| V1 | V2 | Method | Type | What to do |
|---|---|---|---|---|
| `/api/v1/terminals/verify` | `/v2/devices/lookup` | POST | Replaced | Send `macAddress` only |
| `/api/v1/terminals/bind` | `/v2/devices/bind` | POST | Replaced | camelCase; no cloud token or idempotency header |
| `/api/v1/terminals/{id}/unbind` | `/v2/devices/{id}/unbind` | POST | Changed | Optional `cause`; no idempotency header |
| `/api/v1/terminals/{id}/name` | `/v2/devices/{id}/rename` | POST | Renamed | `/name` → `/rename` |
| `/api/v1/me/terminals` | `/v2/devices` | GET | Renamed | Paginated |
| — | `/v2/devices/{id}` | GET | New | Get one device |

### 5.5 Real-time
| V1 | V2 | Type | What to do |
|---|---|---|---|
| Socket.IO `/live-agent` | Socket.IO `/live-agent` | Changed | New token, params and events (§6.9) |
| — | `wss://<host>/v2/assistant/live` | New | Optional JSON alternative |
| `wss://<translation-host>/ws/translate_v2` | `wss://<host>/v2/translation/live` | Replaced | New host, auth and frame format (§6.10) |

---

## 6. Migrating Requests

### 6.1 Sign-up
**Before**
```json
POST /api/v1/auth/signup
{ "email": "user@example.com", "password": "password1", "displayName": "Alex", "phone": "+15551234567" }
```
**After**
```json
POST /v2/auth/sign-up/email
{ "email": "user@example.com", "password": "at-least-12-chars", "name": "Alex" }
```
- `displayName` → `name`
- `phone` removed
- password minimum 8 → 12

**Response**

| | Body | Notes |
|---|---|---|
| Before | `{ "user": { "message": "Registration successful. ...", "email": "user@example.com" } }` | |
| After | `{ "token": null, "user": { "id": "<uuid>", "email": "user@example.com", "name": "Alex", "emailVerified": false, "...": "..." } }` | `token` is `null` until the email is verified. This is normal |

### 6.2 Social sign-in
**Before**
```json
POST /api/v1/auth/signin-oauth
{ "provider": "apple", "idToken": "<id token>", "nonce": "<nonce>" }
```
**After**
```json
POST /v2/auth/sign-in/social
{ "provider": "apple", "idToken": { "token": "<id token>", "nonce": "<nonce>" } }
```

### 6.3 Email codes
**Before**
```json
POST /api/v1/auth/verify-otp
{ "email": "user@example.com", "token": "123456", "type": "signup" }
```
**After**
```json
POST /v2/auth/email-otp/verify-email
{ "email": "user@example.com", "otp": "123456" }
```
- `token` → `otp`.
- There is no `type` on verify: each purpose has its own endpoint (§5.1).
- `type` moves to the send call: `email-verification`, `sign-in`, `forget-password` or `change-email`.

### 6.4 Password reset
**Before**
```json
POST /api/v1/auth/reset-password        { "email": "user@example.com" }
POST /api/v1/auth/verify-otp            { "email": "user@example.com", "token": "123456", "type": "recovery" }
POST /api/v1/auth/update-password       { "password": "newpassword" }   (+ Bearer from verify-otp)
```
**After (code flow)**
```json
POST /v2/auth/email-otp/request-password-reset   { "email": "user@example.com" }
POST /v2/auth/email-otp/reset-password           { "email": "user@example.com", "otp": "123456", "password": "new-password-12+" }
```
- No Bearer token is needed for the reset.
- **A reset signs the user out everywhere.**

**After (link flow)**
```json
POST /v2/auth/request-password-reset   { "email": "user@example.com", "redirectTo": "https://your-app.example/reset" }
POST /v2/auth/reset-password           { "token": "<token from link>", "newPassword": "new-password-12+" }
```

### 6.5 Change password (signed in)
**Before**
```json
POST /api/v1/auth/update-password
{ "password": "newpassword" }
```
**After**
```json
POST /v2/auth/change-password
{ "currentPassword": "old-password", "newPassword": "new-password-12+", "revokeOtherSessions": true }
```

### 6.6 Change email
**Before** (two steps)
```json
POST /api/v1/auth/change-email/request   { "newEmail": "new@example.com", "refreshToken": "<refresh token>" }
POST /api/v1/auth/change-email/verify    { "token": "123456" }
```
**After** (one step + email link)
```json
POST /v2/auth/change-email
{ "newEmail": "new@example.com" }
```
- **Verified account:** the confirmation link is sent to the user's **current** email address. The change completes when they click it. What happens after the click is still being confirmed (§2.3).
- **Unverified account:** the email changes **immediately**, and a verification link is sent to the new address.
- **New email already in use:** the call still returns `{ "status": true }`. No error is returned, so don't rely on this call to detect taken addresses.

Remove the code-entry screen.

### 6.7 Delete account
**Before**
```http
POST /api/v1/auth/delete-account
```
**After**
```http
DELETE /v2/account
Content-Type: application/json

{ "password": "current-password" }
```
- Social-only accounts send no body, but must have signed in within the last **5 minutes**.
- Otherwise the call fails with `403 AUTH_REAUTH_REQUIRED`.

### 6.8 Devices
**Lookup** (was verify)
```json
// Before
POST /api/v1/terminals/verify
{ "mac_ble": "AA:BB:CC:DD:EE:FF", "model": "0215000A", "firmware_ver": "1.7.23" }

// After
POST /v2/devices/lookup
{ "macAddress": "AA:BB:CC:DD:EE:FF" }
```

**Bind**
```http
# Before
POST /api/v1/terminals/bind
Idempotency-Key: bind-7f3a

{ "mac_ble": "AA:BB:CC:DD:EE:FF", "mac_bt": "AA:BB:CC:DD:EE:00", "model": "0215000A", "name": "MyGlass",
  "cloud_token": "<from verify>", "device_token": "17283901", "firmware_ver": "1.7.23", "serial": "MGG02X12261000001" }
```
```http
# After
POST /v2/devices/bind

{ "macAddress": "AA:BB:CC:DD:EE:FF", "macAddressBt": "AA:BB:CC:DD:EE:00", "modelCode": "0215000A", "name": "MyGlass",
  "deviceToken": "17283901", "firmwareVersion": "1.7.23", "serialNumber": "MGG02X12261000001" }
```

| V1 field | V2 field |
|---|---|
| `mac_ble` | `macAddress` |
| `mac_bt` | `macAddressBt` |
| `model` | `modelCode` |
| `device_token` | `deviceToken` |
| `firmware_ver` | `firmwareVersion` |
| `serial` | `serialNumber` |
| `frame_version` | `frameVersion` |
| `os` | `os` |

- **Removed:** `cloud_token`, `claim`, `device_type`, `request_configuration_sn`, and the `Idempotency-Key` header.
- Only `macAddress` is required. `deviceToken` must be 1–20 digits.
- `macAddress` accepts any format (`aa-bb-cc-dd-ee-ff`, `aabbccddeeff`, …).

**Unbind**
```http
# Before
POST /api/v1/terminals/42/unbind
Idempotency-Key: unbind-91c2

{ "reason": "user_initiated" }
```
```http
# After
POST /v2/devices/0192f0c4-…/unbind

{ "cause": "factory_reset" }      // optional; "user_unbind" or "factory_reset"
```

**Rename**
```json
// Before
POST /api/v1/terminals/42/name
{ "name": "MyGlass A1B2" }

// After
POST /v2/devices/0192f0c4-…/rename
{ "name": "MyGlass A1B2" }        // 1–255 characters
```

**List**
```http
# Before
GET /api/v1/me/terminals

# After
GET /v2/devices?limit=50
GET /v2/devices?limit=50&cursor=<nextCursor>
```

### 6.9 Live agent (Socket.IO)
| Item | Before | After |
|---|---|---|
| URL | `https://<host>` + `/live-agent` | `https://<host>` + `/live-agent` (path `/socket.io/`) |
| Auth header | `Authorization: Bearer <JWT>` | `authorization: Bearer <V2 session token>` |
| Query: language | `language` | `app_language` |
| Query: device MAC | `macId` | `device_mac` |
| Query: unchanged | `device_type`, `firmware_version`, `timezone`, `city`, `country`, `current_date`, `current_time` | same |
| Query: new | — | `platform`, `resume_key` |
| Query: removed | `sessionType` | — |
| `audio_stream` | base64 audio | base64 PCM16 16 kHz (same event) |
| `message` | text | text, or `{ text, city?, country? }` |
| `analyze_image` | `{ image, message }` | **Removed.** Use `photo_tool_response` (below) |
| `video_stream`, `stop_agent` | supported | **Removed.** Use `close_session` to hang up |

**Photo requests.** The assistant still asks for a photo with `device_tool_call`, using the same tool names as V1: `thinkar_device_tool_page_take_AI_photo` (photo for AI analysis) and `thinkar_device_tool_page_take_photo`.

| | V1 | V2 |
|---|---|---|
| Request | `device_tool_call` with the photo tool | Same |
| Your reply | Capture the photo, then emit `analyze_image` `{ image, message }` | Capture the photo, then emit **`photo_tool_response`** `{ "status": "ok", "data": { "image": "<base64 JPEG>" } }` |
| QR scans | — | Emit `qr_scan_tool_response` with the same shape |

Keep acknowledging `device_tool_call` within 30 seconds. The exact acknowledgement payload for the photo tool is still being confirmed (§2.3).

### 6.10 Live translation
| Item | Before | After |
|---|---|---|
| URL | `wss://<translation-host>/ws/translate_v2` | `wss://<host>/v2/translation/live` |
| Auth | `?auth_token=<JWT>` | `Authorization` header, cookie, or `?ticket=` (§9.2) |
| Query | `source_lang`, `target_lang` | `source_lang` (default `auto`), `target_lang` (default `en`), `speak=off` (optional), `timezone`, `device_mac` |
| Audio | Binary frames, PCM **Float32** LE, 16 kHz mono | JSON `{"type":"audio","data":"<base64 PCM16 16 kHz mono>"}` |
| Heartbeat | Client sends `{"type":"ping"}` every 25 s | **Server** sends `{"type":"ping"}` every 20 s; reply `{"type":"pong"}`; closed after 90 s silent |
| New messages | — | `audio_end`, `speak {enabled}`, `playback {queuedMs}`, `disconnect` |

Before:
```
<binary Float32 PCM frame>
```
After:
```json
{ "type": "audio", "data": "UklGRiQAAABXQVZF..." }
```

---

## 7. Migrating Responses

### 7.1 Sign-in
**Before**
```json
{
  "user": {
    "session": { "accessToken": "<jwt>", "refreshToken": "<token>", "expiresIn": 3600, "expiresAt": 1760000000,
                 "token_type": "bearer", "email": "user@example.com", "user_id": "<uuid>", "user_role": "User" },
    "profile": { "id": 123, "auth_id": "<uuid>", "name": "Alex", "...": "..." },
    "subscription": null
  }
}
```
**After**
```http
set-auth-token: <session token>
```
```json
{ "redirect": false, "token": "<session token>", "user": { "id": "<uuid>", "email": "user@example.com", "name": "Alex", "emailVerified": true, "...": "..." } }
```

| V1 | V2 |
|---|---|
| `session.accessToken` | `token`, or the `set-auth-token` header (different strings, both valid; §4.3) |
| `session.user_id` | `user.id` |
| `profile.id` (integer) | `user.glassUserId` from `GET /v2/auth/get-session` |
| `refreshToken`, `expiresIn`, `expiresAt`, `token_type` | removed |
| `user_role` | removed (`user.role` is for staff accounts only) |
| `subscription` | see §2.3 |

Social and email-code sign-in follow the same pattern: `access_token` → `token`, and the refresh and expiry fields are removed.

### 7.2 Current user
**Before** (`GET /api/v1/user`)
```json
[ { "id": 123, "auth_id": "<uuid>", "name": "Alex", "email": "user@example.com", "phone": null, "birthday": null, "img": null } ]
```
**After** (`GET /v2/me`)
```json
{ "id": "<uuid>", "email": "user@example.com", "name": "Alex" }
```
**After** (`GET /v2/auth/get-session`, for more detail)
```json
{
  "session": { "id": "<uuid>", "userId": "<uuid>", "expiresAt": "2026-10-14T10:00:00.000Z", "activeOrganizationId": "<uuid>" },
  "user": { "id": "<uuid>", "email": "user@example.com", "name": "Alex", "emailVerified": true, "role": null,
            "glassUserId": 123, "isFirstTimeLogin": false, "mustChangePassword": false, "canChangePassword": true }
}
```
- Array → object.
- `auth_id` → `id`.
- The integer `id` → `glassUserId`.
- Every account has a `glassUserId`. Accounts created in V2 get a new number automatically.

### 7.3 App update check
**Before**
```json
{ "platform": "ios", "latestVersion": "1.8.0", "minSupportedVersion": "1.6.0", "forceUpdate": false, "hasUpdate": true,
  "updateMessage": "...", "storeUrl": "https://...", "releaseNote": "..." }
```
**After**
```json
{ "status": "optional", "release": { "version": "1.8.0", "buildNumber": 210, "notes": "...", "mandatory": false }, "storeUrl": "https://..." }
```

| V1 | V2 |
|---|---|
| `forceUpdate: true` | `status: "forced"` |
| `hasUpdate: true` | `status: "optional"` |
| both `false` / `404` | `status: "up-to-date"`, `release: null` |
| `latestVersion` | `release.version` |
| `releaseNote` | `release.notes` |
| `updateMessage`, `minSupportedVersion`, `platform` | removed |
| — | `release.buildNumber`, `release.mandatory` added |

`storeUrl` can be `null`.

### 7.4 Firmware check
**Before**
```json
{ "hasUpdate": true, "isMandatory": false, "message": "...",
  "firmware": { "id": 42, "version": "1.7.24", "device_type": 6, "releasenotes": "...", "sha256": "...", "is_mandatory": false } }
```
plus a second call for `{ "download_url": "..." }`.

**After**
```json
{
  "status": "update-available",
  "release": { "id": "<uuid>", "version": "1.7.24", "notes": "...", "mandatory": false, "url": "https://...", "sha256": "...", "sizeBytes": 4400000 },
  "rules": { "minBattery": <integer>, "allowWhenCharging": <boolean>, "inactivityTimeoutMs": <integer>, "maxDurationMs": <integer> }
}
```

| V1 | V2 |
|---|---|
| `hasUpdate` | `status` (`update-available`, `up-to-date`, `unknown-model`) |
| `firmware` | `release` |
| `releasenotes` | `release.notes` |
| `isMandatory` / `is_mandatory` | `release.mandatory` |
| `firmware.id` (integer) | `release.id` (UUID); send it as `releaseId` in the report |
| `download_url` (separate call) | `release.url`, **valid 15 minutes** |
| — | `release.sizeBytes`, `rules` added |

`release` and `rules` are `null` unless `status` is `update-available`.

**Report** (was create + patch): send once, at the end.
```json
POST /v2/devices/{id}/firmware/updates
{ "releaseId": "<uuid>", "status": "success", "sdkVersion": "1.0.0", "startedAt": "2026-10-07T10:00:00Z", "endedAt": "2026-10-07T10:05:00Z" }
```
- Response: `{ "id": "<uuid>" }`.
- `startTime` → `startedAt`, `endTime` → `endedAt`, `failureReason` → `error`.
- `status` values are unchanged: `success`, `failed`, `cancelled`, `interrupted`.

### 7.5 Devices
**Lookup** (was verify)
```json
// Before
{ "state": "available", "cloud_token": "...", "cloud_token_ble": 123456789, "expires_at": "...", "ttl_seconds": 90, "terminal": { "...": "..." } }

// After
{ "state": "claimable", "device": { "id": "<uuid>", "macAddress": "AA:BB:CC:DD:EE:FF", "status": "provisioned", "...": "..." } }
```

| V1 state | V2 state |
|---|---|
| `available` | `claimable` |
| `owned_by_you` | `owned_by_me` |
| `owned_by_other` | `owned_by_other` |
| (404 `DEVICE_NOT_PROVISIONED`) | `unregistered` |
| (409 `DEVICE_UNAVAILABLE`) | `blocked` or `retired` |
| `release_directive`, `reserved_by_other` | see §2.3 |

**Device object**
```json
// Before (terminal)
{ "id": 42, "mac_ble": "AA:BB:CC:DD:EE:FF", "mac_bt": "AA:BB:CC:DD:EE:00", "model": "0215000A", "name": "MyGlass",
  "firmware_ver": "1.7.23", "serial": "MGG02X12261000001", "bound_at": "...", "status": "active", "device_token": "17283901" }

// After (device)
{ "id": "<uuid>", "macAddress": "AA:BB:CC:DD:EE:FF", "macAddressBt": "AA:BB:CC:DD:EE:00", "modelId": "<uuid>", "modelCode": "0215000A",
  "name": "MyGlass", "firmwareVersion": "1.7.23", "serialNumber": "MGG02X12261000001", "os": null, "frameVersion": null,
  "status": "provisioned", "boundAt": "...", "lastSeenAt": null, "deviceToken": "17283901" }
```
- `id` is now a **UUID string**.
- `status` now describes the hardware (`provisioned`, `retired`, `blocked`), **not** the binding. A device you own appears in `GET /v2/devices`.

**Other responses**

| Call | Before | After |
|---|---|---|
| Bind | `{ "terminal": {…} }` | the device object (no wrapper) |
| Rename | `{ "terminal": {…} }` | the device object (no wrapper) |
| Unbind | `{ "terminal": {…} }` or `{}` | `{ "released": true \| false }` |
| List | `{ "terminals": [ … ] }` | `{ "devices": [ … ], "nextCursor": "<uuid> \| null" }` |

### 7.6 Live agent events
| V1 | V2 |
|---|---|
| `gemini_session_opened` | `gemini_session_opened { resume_key }`. Keep `resume_key` to resume after a drop |
| `gemini_audio`, `gemini_output_transcript`, `gemini_turn_complete`, `gemini_interrupted` | unchanged |
| `gemini_input_transcript { text }` | `gemini_input_transcript { text, is_final: false }` |
| `device_tool_call` (ack) | unchanged, but **ack within 30 seconds** |
| `gemini_error` | `error { message, code?, retryAfterMs? }` |
| `gemini_response`, `gemini_text_response`, `gemini_request_lost`, `dual_session_error`, `agent_stopped`, `tool_call_started`, `tool_call_ended`, `session_refreshing`, `gemini_reconnecting`, … | removed |
| — | `session_revoked` (the session ended; the socket disconnects) |

### 7.7 Live translation messages
**Before**
```json
{ "source_text": "Hello", "translation": "こんにちは", "complete": true }
```
plus binary TTS frames.

**After**
```json
{ "type": "partial", "sentenceId": "s1", "text": "こんに", "sourceText": "Hel" }
{ "type": "final", "sentenceId": "s1", "text": "こんにちは", "sourceText": "Hello", "detectedLanguage": "en" }
{ "type": "playing_started", "sentenceId": "s1" }
{ "type": "audio", "sentenceId": "s1", "data": "<base64 PCM16 24 kHz mono>" }
{ "type": "playing_finished", "sentenceId": "s1" }
```

| V1 | V2 |
|---|---|
| `source_text` | `sourceText` |
| `translation` / `text` | `text` |
| `complete: false` | `type: "partial"` |
| `complete: true` | `type: "final"` |
| binary audio | `type: "audio"` with base64 **PCM16 at 24 kHz** |
| — | `connected { sessionId }`, `error { message, code?, retryAfterMs? }` |

---

## 8. Error Handling

### 8.1 New error format
**Before** (several formats)
```json
{ "statusCode": 401, "message": "Unauthorized" }
{ "statusCode": 400, "message": "Validation failed", "errors": [ { "path": ["email"], "message": "Invalid email address" } ] }
{ "message": "Validation failed", "errors": [ { "path": "<field>", "message": "...", "metadata": "body" } ] }
{ "code": "OWNED_BY_OTHER", "message": "..." }
```
V1 had two validation formats. `path` was an array on auth and user endpoints, and a string on device and firmware endpoints.
**After** (one format for every error)
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "status": 400,
    "message": "English debug text",
    "details": [ { "field": "email", "code": "<validation code>" } ]
  }
}
```
| Field | How to use it |
|---|---|
| `code` | Branch on this |
| `message` | For logs only; don't show it to users |
| `details` | Validation errors on `/v2` resource endpoints only: field and failure code. Validation errors from `/v2/auth/*` (for example a password under 12 characters) return `VALIDATION_FAILED` **without** `details` |

### 8.2 Authentication errors
| Situation | V1 | V2 |
|---|---|---|
| No / invalid / ended session | 401 | `401 UNAUTHENTICATED` |
| Wrong email or password | 401 | `401 AUTH_INVALID_CREDENTIALS` |
| Email not verified | 403 | `403 AUTH_EMAIL_NOT_VERIFIED` |
| Inactive / banned account | 403 | `403 AUTH_ACCOUNT_BANNED` |
| Wrong or expired code | **401** | **`400 AUTH_INVALID_OTP`** |
| Invalid or expired link token | — | `400 AUTH_INVALID_TOKEN` |
| Email already registered | 409 | `409 AUTH_USER_ALREADY_EXISTS` |
| Account removed by support | — | `401 ACCOUNT_DELETED_BY_ADMIN` |
| Must change password | — | `403 AUTH_MUST_CHANGE_PASSWORD` |
| Recent sign-in required | — | `403 AUTH_REAUTH_REQUIRED` |
| Too many attempts | — | `429 RATE_LIMITED` + `retry-after` header |

A wrong email code is now **400, not 401**. Don't treat it as "signed out".

### 8.3 Validation errors
| | V1 | V2 |
|---|---|---|
| Status | 400 | `400 VALIDATION_FAILED` |
| Field list | `errors[].path` (array or string), `errors[].message` | `details[].field`, `details[].code` on `/v2` resource endpoints; **no `details`** on `/v2/auth/*` |
| Password length | 8 minimum | 12–128 → `VALIDATION_FAILED` |
| Device token format | `422 DEVICE_TOKEN_INVALID` | `422 DEVICE_TOKEN_INVALID` (unchanged) |

### 8.4 Permission and device errors
| Situation | V1 | V2 |
|---|---|---|
| Not your device | `403 FORBIDDEN` | `403 DEVICE_NOT_OWNED` |
| Device not registered | `404 DEVICE_NOT_PROVISIONED` | `404 DEVICE_NOT_PROVISIONED` |
| Bound to another account | `409 OWNED_BY_OTHER` | `409 DEVICE_ALREADY_OWNED` |
| Device blocked | `409 DEVICE_UNAVAILABLE` | `409 DEVICE_BLOCKED` |
| Device retired | `409 DEVICE_UNAVAILABLE` | `404 DEVICE_NOT_PROVISIONED` |
| Bind collided with another change | — | `409 DEVICE_CONTENDED`: retry |
| Unbind an unknown id | `404 NOT_FOUND` | `200 { "released": false }` |
| Rename an unknown id | `404 NOT_FOUND` | `403 DEVICE_NOT_OWNED` |
| Get / firmware on an unknown id | — | `404 DEVICE_NOT_FOUND` |
| Cloud token expired | `410 CLOUD_TOKEN_EXPIRED` | no longer exists |
| Idempotency errors | `400` / `422` | no longer exist |
| Claim rate limit | `429 CLAIM_RATE_LIMITED` | no longer exists |
| Staff-only action | `403` | `403 FORBIDDEN` |

### 8.5 Other changes
| Situation | V1 | V2 |
|---|---|---|
| App update check with no config | `404` | Never 404; always `200` with `status` |
| Firmware storage unavailable | — | `503` |
| Account is the only owner of a shared workspace (delete) | — | `409 ACCOUNT_SOLE_OWNER` |

### 8.6 Real-time errors
| Channel | V2 behavior |
|---|---|
| Socket.IO `/live-agent` | Auth failure → `connect_error`. Runtime → `error { message, code?, retryAfterMs? }` (`code`: `service_error`, `timeout`, `rate_limited`). Session ended → `session_revoked` |
| WebSockets (`/v2/assistant/live`, `/v2/translation/live`) | `{ "type": "error", ... }` frames; close codes below |

| Close code | Meaning | What to do |
|---|---|---|
| `4401` | Not authenticated | Sign in again, then reconnect |
| `4500` | Service not configured, switched off, or failed to start | Show an error; retry later |
| `4503` | Server restarting or too busy | Reconnect after a short delay |

---

## 9. Client Migration

### 9.1 Web applications
1. **Base URL:** `/api/v1` → `/v2`.
2. **Auth:** remove token storage and the `Authorization` header. Send every request with `credentials: "include"`. The browser keeps the session cookie (`HttpOnly`, `SameSite=Lax`, `Secure` on HTTPS, 7 days).
3. **CORS:** your origin must be on the V2 allowlist; ask the API team. Unlisted origins get no credentialed CORS response.
4. **Redirect URLs:** any `callbackURL` / `redirectTo` you send to `/v2/auth/*` must be on the trusted list, or the call returns `403`.
5. **Sessions:** remove refresh timers. On `401`, go to sign-in.
6. **WebSockets:** browsers can't set headers on a WebSocket. Use the cookie (same site), or get a ticket and connect with `?ticket=` (§9.2).
7. **Errors:** read `error.code` everywhere.

```js
// Sign in
await fetch("https://<host>/v2/auth/sign-in/email", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});

// Authenticated call
const me = await fetch("https://<host>/v2/me", { credentials: "include" }).then(r => r.json());
```

### 9.2 WebSocket authentication (all clients)
Options for `/v2/assistant/live` and `/v2/translation/live`, in order of preference:
1. **Ticket:** call `GET /v2/auth/one-time-token/generate` while signed in, then connect with `wss://<host>/v2/translation/live?ticket=<ticket>&…`. A ticket works **once** and expires after **1 minute**.
2. **Header or cookie** on the connection: `Authorization: Bearer <session token>`, or the session cookie.
3. `?token=<session token>` works **only outside production**. Don't ship it.

Socket.IO `/live-agent` accepts **only** the `authorization` header.

### 9.3 Mobile applications
1. **Base URLs:** REST `https://<host>/v2`; Socket.IO `https://<host>` (`/live-agent`); translation `wss://<host>/v2/translation/live`. Remove the separate translation host.
2. **Token storage:** replace the JWT + refresh token with **one session token** taken from the `set-auth-token` header. Keep it in secure storage.
3. **Requests:** keep `Authorization: Bearer <session token>`.
4. **`x-install-id`:** generate a UUID on first launch, persist it, and send it on every sign-in.
5. **Sessions:** delete refresh logic. On `401` return to sign-in. A sign-in on a newer phone signs this phone out.
6. **Sign-out (in this order):** `DELETE /v2/me/push-token` → `POST /v2/auth/sign-out` → clear local data. Removing the push token after sign-out fails with `401`.
7. **Push (optional):** `PUT /v2/me/push-token` after sign-in, with `{ "platform": "ios" | "android", "token": "<Expo push token>" }`.
8. **Removed glasses (optional):** call `GET /v2/me/device-removals` when the app returns to the foreground.
9. **Ids:** store user ids and device ids as **strings** (UUIDs). Use `glassUserId` wherever the old numeric user id was sent to the glasses.
10. **Binding:**
    - Replace verify → bind with lookup → bind.
    - Remove the `Idempotency-Key` and cloud-token handling.
    - Read `deviceToken` from bind / list / get.
11. **Firmware:**
    - Check per device, download from `release.url` within 15 minutes, report once at the end.
    - Remove the old create/patch retry queue.
12. **App update check:** send `build` (integer build number) and `osVersion`; show the prompt from `status`.
13. **Live agent:** follow §6.9 and §7.6.
14. **Live translation:** follow §6.10 and §7.7. Encode microphone audio as **16-bit PCM**, base64, inside JSON.

### 9.4 Other API clients (servers, scripts, SDKs)
1. **Base URL:** `/api/v1` → `/v2`.
2. **Sign in:** `POST /v2/auth/sign-in/email`. Store the `set-auth-token` value and send it as `Authorization: Bearer`.
3. **No refresh:** when you get `401`, sign in again.
4. **JWTs:** don't use the JWT from `GET /v2/auth/token` for `/v2` calls; it isn't accepted.
5. **Rate limits:** respect `429` and the `retry-after` header (e.g. sign-in allows 5 attempts per minute).
6. **Schema:** generate or check models against `GET /openapi.json`.
7. **Errors:** read `error.code`.

---

## 10. Complete Migration Checklist

**Preparation**
- [ ] Get the V2 host for every environment.
- [ ] Web: get your origin added to the allowlist. Mobile: register your deep-link scheme if you use magic links.
- [ ] Check §2.3 and resolve any items your app depends on.
- [ ] Download `openapi.json` from your target environment.

**Configuration**
- [ ] Switch REST to `https://<host>/v2`.
- [ ] Switch Socket.IO to `https://<host>` (`/live-agent`).
- [ ] Switch live translation to `wss://<host>/v2/translation/live`.

**Authentication**
- [ ] Remove access/refresh token storage, the refresh call and expiry timers.
- [ ] Mobile/API: store the session token from `set-auth-token`; send `Authorization: Bearer`.
- [ ] Web: drop the `Authorization` header; use `credentials: "include"`.
- [ ] Mobile: create, persist and send `x-install-id` on sign-in.
- [ ] Update sign-in: email, social (`idToken` object), email code.
- [ ] Update sign-up: `name`, 12–128 character passwords, code verification.
- [ ] Update password reset, change password (`currentPassword`) and change email (link).
- [ ] Update sign-out: `DELETE /v2/me/push-token` **first**, then `POST /v2/auth/sign-out`.
- [ ] Sign-up: treat `token: null` in the response as "verification pending", not an error.
- [ ] Mobile/API: store either the `set-auth-token` header or the body `token`, and use only that one.
- [ ] Update account deletion: `DELETE /v2/account` with `password`.
- [ ] Route `401` to sign-in, `403 AUTH_MUST_CHANGE_PASSWORD` to change-password, and `403 AUTH_REAUTH_REQUIRED` to re-auth.

**User data**
- [ ] `GET /user` → `GET /v2/me` or `GET /v2/auth/get-session`.
- [ ] User ids as strings; use `glassUserId` for the glasses.

**Devices**
- [ ] `terminals/verify` → `devices/lookup`; map the new states.
- [ ] `terminals/bind` → `devices/bind` (camelCase, no cloud token, no idempotency header).
- [ ] `unbind` with optional `cause`; `/name` → `/rename`.
- [ ] `me/terminals` → `GET /v2/devices` with pagination.
- [ ] Device ids as strings; update the meaning of `status`.

**Firmware and app updates**
- [ ] Firmware check per device; download within 15 minutes; one report at the end.
- [ ] App update check with `build` + `osVersion`; render `status`.

**Real-time**
- [ ] Live agent: V2 token, `app_language`, `device_mac`, `resume_key`; remove `analyze_image` / `video_stream` / `stop_agent`; handle `error` and `session_revoked`; ack tool calls within 30 s.
- [ ] Live translation: new URL and auth, JSON frames, base64 PCM16 upload, `pong` replies, `partial` / `final` / `audio`, close codes.

**Errors**
- [ ] One error parser reading `error.code`.
- [ ] Handle `429` with `retry-after`.
- [ ] Wrong email code = `400 AUTH_INVALID_OTP` (not `401`).

**Testing**
- [ ] A V1 account signs in with its existing password, Google and Apple.
- [ ] Glasses bound in V1 appear in `GET /v2/devices` with a `deviceToken` and reconnect.
- [ ] Sign-out ends the session (the next call returns `401`).
- [ ] Signing in on a second phone signs the first one out.
- [ ] A password reset signs out every device.
- [ ] Firmware update end to end, including the report.
- [ ] Live agent and live translation sessions, including a reconnect.
- [ ] Every error your UI handles.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Every call returns `404 NOT_FOUND` | Still using `/api/v1/...` | Use `/v2/...` |
| `401` right after the update | V1 token in use | Sign in again with V2 |
| `401` on calls although sign-in worked | Token not sent, or the JWT from `/v2/auth/token` used | Send the `set-auth-token` value as `Authorization: Bearer` |
| Browser: signed in but the next call is `401` | Cookie not sent | Add `credentials: "include"`; check the origin is allowlisted |
| Browser: CORS error | Origin not on the allowlist | Ask the API team to add it |
| `403` on sign-in or reset with a `callbackURL` / `redirectTo` | URL not trusted | Use an allowlisted URL |
| Phone A gets `401` after phone B signs in | One phone per account | Expected; phone A must sign in again |
| Everyone was signed out | Password reset, or the account was deleted | Expected; sign in again |
| `401 ACCOUNT_DELETED_BY_ADMIN` | Account removed by support | Sign the user out and show a message |
| `403 AUTH_MUST_CHANGE_PASSWORD` on every call | Account flagged to change password | Call `POST /v2/auth/change-password` |
| `403 AUTH_REAUTH_REQUIRED` on account deletion | Wrong/missing password, or a social account signed in > 5 min ago | Send `password`, or sign in again first |
| `400 VALIDATION_FAILED` on sign-up or reset | Password under 12 characters, or a field renamed | Auth endpoints return no `details`: check the password length (12–128) and the field names `name`, `otp`, `newPassword` |
| Phone keeps getting pushes after sign-out | Push token removed after sign-out (got `401`) | Call `DELETE /v2/me/push-token` before `POST /v2/auth/sign-out` |
| Sign-up response has `token: null` | Expected: email not verified yet | Continue to code verification |
| V1 user can't sign in: `AUTH_EMAIL_NOT_VERIFIED` | Email was never verified in V1 | Send a code with `type: "email-verification"` and verify |
| V1 user can't sign in with password | Had an expired temporary password in V1 | Use password reset |
| V1 glasses not in `GET /v2/devices` | V1 binding wasn't valid (§2.2) | Bind the glasses again |
| `400 AUTH_INVALID_OTP` | Wrong/expired code, or too many attempts | Request a new code |
| `429 RATE_LIMITED` | Too many auth attempts | Wait for `retry-after` seconds |
| Bind returns `409 DEVICE_ALREADY_OWNED` | Glasses belong to another account | The other account must unbind (factory-reset takeover isn't available, §2.3) |
| Bind returns `409 DEVICE_CONTENDED` | Bind collided with another change | Retry |
| Bind returns `422 DEVICE_TOKEN_INVALID` | `deviceToken` isn't 1–20 digits | Send the numeric string from the glasses |
| Device calls return `400` on the id | Integer V1 id used | Use the UUID from `GET /v2/devices` |
| Firmware download fails with an expired link | `release.url` is older than 15 minutes | Call the firmware check again |
| App update check returns `400` | Missing `build` or `osVersion`, or version string sent | Send the integer build number and `osVersion` |
| Live agent fails to connect (`connect_error`) | Missing or V1 token in the handshake | Send `authorization: Bearer <V2 session token>` |
| Live agent: images not processed | `analyze_image` is no longer handled | Use `photo_tool_response` / `qr_scan_tool_response` (§6.9) |
| Translation socket closes with `4401` | No valid auth on connect | Use the header, cookie or a fresh `?ticket=` |
| Translation socket closes after ~90 s | No `pong` replies | Reply `{"type":"pong"}` to every `ping` |
| Translation returns no text | Audio sent as binary Float32 | Send JSON with base64 PCM16 16 kHz |
| WebSocket closes with `4503` | Server restarting or at capacity | Reconnect after a short delay |

---

## 12. V1 → V2 Reference Table

| V1 | V2 |
|---|---|
| `https://<host>/api/v1` | `https://<host>/v2` |
| `Authorization: Bearer <JWT>` | `Authorization: Bearer <session token>` (mobile/API) · cookie (web) |
| `POST /api/v1/auth/signup` | `POST /v2/auth/sign-up/email` |
| `POST /api/v1/auth/signin` | `POST /v2/auth/sign-in/email` |
| `POST /api/v1/auth/signin-oauth` | `POST /v2/auth/sign-in/social` |
| `POST /api/v1/auth/refresh` | — (removed) |
| `POST /api/v1/auth/signout` | `POST /v2/auth/sign-out` |
| `POST /api/v1/auth/send-otp` | `POST /v2/auth/email-otp/send-verification-otp` |
| `POST /api/v1/auth/verify-otp` (signup) | `POST /v2/auth/email-otp/verify-email` |
| `POST /api/v1/auth/verify-otp` (magiclink / email) | `POST /v2/auth/sign-in/email-otp` |
| `POST /api/v1/auth/verify-otp` (recovery) | `POST /v2/auth/email-otp/reset-password` |
| `POST /api/v1/auth/resend-verification` | `POST /v2/auth/email-otp/send-verification-otp` |
| `POST /api/v1/auth/reset-password` | `POST /v2/auth/email-otp/request-password-reset` · `POST /v2/auth/request-password-reset` |
| `POST /api/v1/auth/update-password` (recovery) | `POST /v2/auth/email-otp/reset-password` · `POST /v2/auth/reset-password` |
| `POST /api/v1/auth/update-password` (signed in) | `POST /v2/auth/change-password` |
| `POST /api/v1/auth/change-email/request` | `POST /v2/auth/change-email` |
| `POST /api/v1/auth/change-email/verify` | — (removed; email link) |
| `POST /api/v1/auth/delete-account` | `DELETE /v2/account` |
| `GET /api/v1/user` | `GET /v2/me` · `GET /v2/auth/get-session` |
| `GET /api/v1/app-version/check` | `GET /v2/app-releases/check` |
| `GET /api/v1/firmware/latest/{deviceType}` | `GET /v2/devices/{id}/firmware/check` |
| `GET /api/v1/firmware/download/{firmwareId}` | — (`release.url` in the check) |
| `POST /api/v1/firmware/update-log` | `POST /v2/devices/{id}/firmware/updates` |
| `PATCH /api/v1/firmware/update-log/{id}` | — (merged into the report) |
| `POST /api/v1/terminals/verify` | `POST /v2/devices/lookup` |
| `POST /api/v1/terminals/bind` | `POST /v2/devices/bind` |
| `POST /api/v1/terminals/{id}/unbind` | `POST /v2/devices/{id}/unbind` |
| `POST /api/v1/terminals/{id}/name` | `POST /v2/devices/{id}/rename` |
| `GET /api/v1/me/terminals` | `GET /v2/devices` |
| — | `GET /v2/devices/{id}` |
| — | `GET /v2/auth/get-session` |
| — | `PUT` / `DELETE /v2/me/push-token` |
| — | `GET /v2/me/device-removals` |
| — | `GET /v2/auth/one-time-token/generate` |
| Socket.IO `/live-agent` | Socket.IO `/live-agent` (updated) · `wss://<host>/v2/assistant/live` (new) |
| `wss://<translation-host>/ws/translate_v2` | `wss://<host>/v2/translation/live` |
| `Idempotency-Key` header | — (removed) |
| — | `x-install-id` header (mobile sign-in) |

**Field renames (most common)**

| V1 | V2 |
|---|---|
| `accessToken` / `access_token` | `token` |
| `displayName` | `name` |
| `token` (email code) | `otp` |
| `password` (change password) | `newPassword` (+ `currentPassword`) |
| `mac_ble` | `macAddress` |
| `mac_bt` | `macAddressBt` |
| `model` | `modelCode` |
| `device_token` | `deviceToken` |
| `firmware_ver` | `firmwareVersion` |
| `serial` | `serialNumber` |
| `frame_version` | `frameVersion` |
| `bound_at` | `boundAt` |
| `terminal` / `terminals` | device / `devices` |
| `startTime` / `endTime` / `failureReason` | `startedAt` / `endedAt` / `error` |
| `releasenotes` | `notes` |
| `is_mandatory` / `isMandatory` | `mandatory` |
| `download_url` | `release.url` |
| `source_text` / `translation` / `complete` | `sourceText` / `text` / `type: partial \| final` |
| `language` (live agent query) | `app_language` |
| `macId` (live agent query) | `device_mac` |
