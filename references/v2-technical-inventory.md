# V2 Technical Inventory

This document describes how API V2 works: authentication, structure, endpoints, models, errors and client integration.

---

## A. Authentication

### A.1 Model
- V2 uses **server-side sessions**. A session is identified by an opaque **session token**, not a self-contained JWT.
- Every protected request is checked against the server's session store.
- The same session can be presented in either of two ways:

  | Client | How to send the session |
  |---|---|
  | Browser | Session cookie |
  | Native / mobile / server | `Authorization: Bearer <session_token>` |

- A JWT endpoint exists (`GET /v2/auth/token`), but **a JWT is not accepted** as a credential on `/v2` resource routes. Use the session token.

### A.2 Getting the session token
Every call that creates a session returns the token in two places:
- the **`set-auth-token` response header** (listed in `Access-Control-Expose-Headers`), and
- the `token` field of the JSON body.

Both work as `Authorization: Bearer`, but they are **different strings**: the header carries a signed form of the token, the body carries the plain token. Store one and use it consistently.

### A.3 Sign-in and sign-up endpoints (all public)
| Flow | Endpoint | Request | Success response |
|---|---|---|---|
| Email + password | `POST /v2/auth/sign-in/email` | `{ email, password, rememberMe?, callbackURL? }` | `{ redirect, token, user }` (+ `url` only when `callbackURL` is sent) |
| Google / Apple | `POST /v2/auth/sign-in/social` | `{ provider, idToken: { token, nonce?, accessToken? } }` | `{ redirect: false, token, user }` |
| Email code sign-in | `POST /v2/auth/email-otp/send-verification-otp` `{ email, type: "sign-in" }`, then `POST /v2/auth/sign-in/email-otp` `{ email, otp }` | | `{ token, user }` |
| Magic link | `POST /v2/auth/sign-in/magic-link` `{ email }`. The email link opens `https://<host>/magic-link-open?token=…`, which redirects to the app deep link `<scheme>://magic-link-verify?token=…`. The app then calls `GET /v2/auth/magic-link/verify?token=…` | | `{ token, user, session }` |
| Sign-up | `POST /v2/auth/sign-up/email` | `{ email, password, name }` | `{ token: null, user }`. A 6-digit code is emailed. **No session until the email is verified**; `token: null` is expected |
| Verify sign-up code | `POST /v2/auth/email-otp/verify-email` | `{ email, otp }` | `{ status: true, token, user }`. Signs the user in |
| Resend verification code | `POST /v2/auth/email-otp/send-verification-otp` | `{ email, type: "email-verification" }` | `{ success: true }` |

Rules:
- **Password:** 12–128 characters.
- **Unverified email:** sign-in fails with `AUTH_EMAIL_NOT_VERIFIED`.
- **Existing email:** sign-up fails with `AUTH_USER_ALREADY_EXISTS`.
- **Email code sign-in:** creates the account if none exists for the email.
- **LINE:** uses a browser redirect flow, not the ID-token call above. Details are still being confirmed.

### A.4 Sign-out
Steps, in this order:
1. Mobile apps registered for push: `DELETE /v2/me/push-token` with `{ token }`, **while the session is still valid**. After sign-out this call returns `401`.
2. `POST /v2/auth/sign-out` → `{ "success": true }`. The session is **deleted on the server**, so the token stops working immediately.

### A.5 What happens when a session is created
- **One phone per account.** If the sign-in request carries an **`x-install-id`** header (a UUID per app install), every **older** phone session of that user is signed out. The previous phone gets `401` on its next call.
- Sessions without `x-install-id` (web, dashboard) are not affected.
- Signing in cancels a pending account deletion (§C.3).

### A.6 Session lifetime and expiry
| Property | Behavior |
|---|---|
| Lifetime | **7 days** |
| Sliding renewal | An active session's expiry is extended once a day when it's used |
| Refresh token | **None.** There is no token refresh call |
| Freshness | Some sensitive actions need a recent sign-in; otherwise `403 AUTH_REAUTH_REQUIRED` |
| Ended by | Sign-out, a newer phone signing in, a password reset (ends **all** sessions), account deletion |
| Account removed by staff | Requests return `401 ACCOUNT_DELETED_BY_ADMIN` |
| Forced password change | Users flagged for it get `403 AUTH_MUST_CHANGE_PASSWORD` on all `/v2` routes until they change it |
| Live calls | A live-agent call whose session ends is closed; the client receives `session_revoked` |

### A.7 Cookie (browser clients)
| Attribute | Value |
|---|---|
| Name | `__Secure-better-auth.session_token` on HTTPS (`better-auth.session_token` on plain HTTP) |
| HttpOnly | Yes |
| Secure | Yes on HTTPS |
| SameSite | `Lax` |
| Path | `/` |
| Domain | Parent domain when the deployment shares cookies across subdomains; otherwise host-only |
| Max-Age | 7 days. With `rememberMe: false` it's a browser-session cookie |

### A.8 CSRF and origin protection
- There is no CSRF token.
- Protection comes from these mechanisms:
  - The `SameSite=Lax` session cookie.
  - Credentialed CORS only for allowlisted origins (§F.3).
  - An origin check on non-GET `/v2/auth/*` requests. `Origin`, `callbackURL`, `redirectTo`, `errorCallbackURL` and `newUserCallbackURL` must be trusted origins, otherwise `403`.

### A.9 Request pipeline
1. Security headers and client-IP detection on every request. A caller-supplied `x-client-ip` is discarded.
2. CORS on `/v2/*`.
3. **Deny by default:** every `/v2/*` route requires a valid session, except the public routes below.

**Public routes:**
- Everything under `/v2/auth/*`. It checks the session itself where needed.
- `GET /v2/app-releases/check`.
- `GET /v2/assistant/live` and `GET /v2/translation/live`. These authenticate inside the WebSocket.

### A.10 Authorization
- **Customer endpoints have no roles.** Every device call is scoped to the signed-in user; ids sent in a body are never trusted as the owner.
- **Staff endpoints** require a staff role: `staff` (read), `admin` or `super-admin` (read + manage). They may also require two-factor authentication. Otherwise `403`.
- **Organization roles** (e.g. `owner`) apply to workspace management. Every user gets a personal workspace on first sign-in.

### A.11 Unauthorized responses
| Channel | Response |
|---|---|
| HTTP | `401 { "error": { "code": "UNAUTHENTICATED", "status": 401, "message": "..." } }` |
| WebSocket `/v2/*/live` | Connection accepted, then closed with code **4401** "Authentication required" |
| Socket.IO `/live-agent` | Connection refused (`connect_error`): "Authentication required", "Invalid session" or "Auth error" |

### A.12 Rate limits on auth endpoints
Default: 100 requests per minute. Stricter, per minute:

| Endpoint | Limit |
|---|---|
| `/sign-in/email` | 5 |
| `/sign-up/email` | 5 |
| `/reset-password` | 5 |
| `/email-otp/verify-email` | 5 |
| `/email-otp/check-verification-otp` | 5 |
| `/request-password-reset` | 3 |
| `/send-verification-email` | 3 |
| `/change-email` | 3 |
| `/email-otp/send-verification-otp` | 3 |
| `/sign-in/magic-link` | 3 |
| `/get-session` | 600 |

When limited: `429 RATE_LIMITED` with a `retry-after` header.

---

## B. API Structure

| Item | Value |
|---|---|
| REST base | **`https://<host>/v2`** |
| Auth base | `/v2/auth/*` |
| Health | `GET /livez`, `GET /readyz`, `GET /health` (public, unversioned) |
| API reference | `GET /openapi.json`, `GET /docs` |
| Raw WebSockets | `wss://<host>/v2/assistant/live`, `wss://<host>/v2/translation/live` |
| Socket.IO | Namespace **`/live-agent`** on the default `/socket.io/` path of the same host (not under `/v2`) |
| Unknown route | `404 { "error": { "code": "NOT_FOUND", ... } }` |

**Endpoint groups:**

| Group | Purpose |
|---|---|
| `/v2/auth/*` | Sign-up, sign-in, sessions, passwords, email |
| `/v2/me` | Current user, push token, device removals |
| `/v2/account` | Account deletion |
| `/v2/org` | Current workspace |
| `/v2/devices` | Customer device binding and firmware |
| `/v2/app-releases` | App update check |
| `/v2/assistant` | Assistant preferences (+ live WebSocket) |
| `/v2/translation` | Live translation WebSocket |
| `/v2/contacts`, `/v2/reports`, `/v2/teleprompter/sessions`, `/v2/sports/nba` | Feature APIs |
| `/v2/admin/*`, `/v2/dashboard/*`, `/v2/agent-tests` | Staff only |

---

## C. Endpoint Inventory

### C.1 Session and password
| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| POST | `/v2/auth/sign-out` | Session | — | `{ success: true }` |
| GET | `/v2/auth/get-session` | Session | — | `{ session, user }` (§D.2) |
| POST | `/v2/auth/change-password` | Session | `{ currentPassword, newPassword, revokeOtherSessions? }` | success body |
| POST | `/v2/auth/email-otp/request-password-reset` | Public | `{ email }` | `{ success: true }` |
| POST | `/v2/auth/email-otp/check-verification-otp` | Public | `{ email, otp, type: "forget-password" }` | check only |
| POST | `/v2/auth/email-otp/reset-password` | Public | `{ email, otp, password }` | success body; **ends all sessions** |
| POST | `/v2/auth/request-password-reset` | Public | `{ email, redirectTo? }` | link-based reset email |
| POST | `/v2/auth/reset-password` | Public | `{ newPassword, token }` | success body; **ends all sessions** |
| POST | `/v2/auth/change-email` | Session | `{ newEmail, callbackURL? }` | `{ status: true }` (see below) |
| GET | `/v2/auth/one-time-token/generate` | Session | — | one-time WebSocket ticket (§F.2) |

- Email-code `type` values: `email-verification`, `sign-in`, `forget-password`, `change-email`.
- **Change email:**

  | Situation | Result |
  |---|---|
  | Verified account | A confirmation link goes to the **current** email address. What happens after the click is still being confirmed |
  | Unverified account | The email changes immediately; a verification link goes to the new address |
  | New email already in use | Still returns `{ status: true }`; no error |
- Password-reset requests return the same success response whether or not the account exists.

### C.2 Current user
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v2/me` | — | `{ id, email, name }` (`id` is a UUID) |
| PUT | `/v2/me/push-token` | `{ platform: "ios" \| "android", token: <Expo push token>, appBuild? }` | `{ ok: true }` |
| DELETE | `/v2/me/push-token` | `{ token }` | `{ ok: true }` (always) |
| GET | `/v2/me/device-removals?since=<ISO-8601>` | — | `{ removals: [ { deviceId, macAddress, name, removedAt } ] }`. Glasses removed by staff; default window 30 days, newest first |

### C.3 Account deletion
`DELETE /v2/account`. Body `{ password? }` → `{ success: true }`.

- **Re-authentication is required:**
  - Accounts with a password must send `password`.
  - Social-only accounts must have signed in within the last **5 minutes**.
  - Otherwise `403 AUTH_REAUTH_REQUIRED`, limited to 5 failed attempts per 15 minutes.
- `409 ACCOUNT_SOLE_OWNER` if the user is the only owner of a workspace other people use.
- On success:
  - The account is marked for deletion and permanently erased after **30 days**. Signing in during that time cancels the deletion.
  - The user's glasses are released immediately, and stay released even if the deletion is cancelled.
  - All sessions end.

### C.4 App update check
`GET /v2/app-releases/check` (public)

| Query | Required | Example |
|---|---|---|
| `platform` | yes | `ios` or `android` |
| `build` | yes | `210` (app build number, integer) |
| `osVersion` | yes | iOS: `17.2`; Android: `34` (API level) |

Response `200`:
```json
{
  "status": "up-to-date | optional | forced",
  "release": { "version": "1.8.0", "buildNumber": 210, "notes": "...", "mandatory": false },
  "storeUrl": "https://..."
}
```
- `release` is `null` when `status` is `up-to-date`.
- `storeUrl` can be `null`.
- The server makes the whole decision; the app only renders `status`.
- Errors: `400` invalid params, `429` (60 requests per minute per IP).

### C.5 Devices
All `/v2/devices` routes need a session and act only on the signed-in user's devices.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v2/devices/lookup` | `{ macAddress }` | `{ state, device }` |
| POST | `/v2/devices/bind` | `{ macAddress, serialNumber?, macAddressBt?, name?, firmwareVersion?, os?, frameVersion?, modelCode?, deviceToken? }` | Device |
| GET | `/v2/devices?limit=&cursor=` | — | `{ devices: [Device], nextCursor }` |
| GET | `/v2/devices/{id}` | — | Device |
| POST | `/v2/devices/{id}/rename` | `{ name }` (1–255, trimmed) | Device |
| POST | `/v2/devices/{id}/unbind` | optional `{ cause: "user_unbind" \| "factory_reset" }` | `{ released: boolean }` |

**Lookup.** Check a MAC before binding. It's read-only.

| `state` | Meaning |
|---|---|
| `unregistered` | MAC not in the registry |
| `claimable` | Free to bind |
| `owned_by_me` | Already yours |
| `owned_by_other` | Bound to another account |
| `blocked` | Blocked by staff |
| `retired` | Retired |

`device` is the registry entry, or `null`. It never includes the owner or `deviceToken`.

**Bind.**
- Binds the device to the signed-in user.
- Repeating it for a device you already own is a safe retry: it updates the reported facts and returns success.
- `deviceToken` (optional): numeric string, 1–20 digits.

| Status | Code |
|---|---|
| `400` | `VALIDATION_FAILED` (bad MAC) |
| `404` | `DEVICE_NOT_PROVISIONED` |
| `409` | `DEVICE_ALREADY_OWNED`, `DEVICE_BLOCKED`, `DEVICE_CONTENDED` (retry) |
| `422` | `DEVICE_TOKEN_INVALID` |

**List.** Oldest binding first.
- `limit` defaults to 50; values above 100 are capped to 100.
- Pass the previous `nextCursor` as `cursor`. It's `null` on the last page.

**Rename.** Call it after the rename on the glasses succeeds.
- `403 DEVICE_NOT_OWNED`.

**Unbind.**
- `factory_reset` records that the glasses were just wiped.
- Unbinding an already-released device returns `{ released: false }`.
- `403 DEVICE_NOT_OWNED`.

**Get.** `404 DEVICE_NOT_FOUND`.

### C.6 Firmware
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v2/devices/{id}/firmware/check?currentVersion=<version>` | — | Check result |
| POST | `/v2/devices/{id}/firmware/updates` | Report | `{ id }` |

**Check result:**
```json
{
  "status": "update-available | up-to-date | unknown-model",
  "release": { "id": "uuid", "version": "1.7.24", "notes": "...", "mandatory": false, "url": "https://...", "sha256": "...", "sizeBytes": 4400000 },
  "rules": { "minBattery": "<integer>", "allowWhenCharging": "<boolean>", "inactivityTimeoutMs": "<integer>", "maxDurationMs": "<integer>" }
}
```
- `currentVersion` is required: the version the glasses report right now.
- `release` and `rules` are `null` unless `status` is `update-available`.
- `url` is a signed download link valid for **15 minutes**.
- `update-blocked` and `no-firmware` exist in the schema but are never returned.
- Errors: `400` missing `currentVersion`, `404 DEVICE_NOT_FOUND`, `503` firmware storage unavailable.

**Report** (send once, at the end of an install attempt):
```json
{ "releaseId": "uuid", "status": "success | failed | cancelled | interrupted", "error": "optional text, max 2000", "sdkVersion": "1.0.0", "startedAt": "ISO-8601", "endedAt": "ISO-8601" }
```
- Errors: `400 VALIDATION_FAILED` (unknown `releaseId`, or one for a different model), `404 DEVICE_NOT_FOUND`.

### C.7 Real-time: AI assistant (Socket.IO)
| Item | Value |
|---|---|
| URL | `https://<host>` with namespace `/live-agent` (path `/socket.io/`) |
| Auth | Handshake header `authorization: Bearer <session_token>` (only the header is accepted) |
| Handshake query | `device_mac`, `device_type`, `firmware_version`, `platform`, `timezone`, `city`, `country`, `current_date`, `current_time`, `app_language`, `resume_key` |

Client → server:

| Event | Payload |
|---|---|
| `audio_stream` | base64 PCM16, 16 kHz |
| `message` | string, or `{ text, city?, country? }` |
| `photo_tool_response` | `{ status: "ok", data: { image: <base64> } }` |
| `qr_scan_tool_response` | `{ status: "ok", data: { image: <base64> } }` |
| `close_session` | Hang up |

Server → client:

| Event | Payload |
|---|---|
| `gemini_session_opened` | `{ resume_key }`. Keep it; pass it as `resume_key` to resume after a drop |
| `gemini_audio` | `{ data }` (base64 PCM16) |
| `gemini_output_transcript` | `{ text }` |
| `gemini_input_transcript` | `{ text, is_final: false }` |
| `gemini_turn_complete` | — |
| `gemini_interrupted` | Stop playback |
| `error` | `{ message, code?, retryAfterMs? }`. `code`: `service_error`, `timeout`, `rate_limited` |
| `device_tool_call` | `{ tool, args }`. **Acknowledge within 30 s** with the result, otherwise it's treated as a failed tool call |
| `session_revoked` | The session ended; the socket is disconnected |

If the assistant service isn't configured, the server emits `error` "Provider not configured" and disconnects.

**Photo requests.** The assistant asks for a photo with `device_tool_call` (tools `thinkar_device_tool_page_take_AI_photo` and `thinkar_device_tool_page_take_photo`). The client captures the photo and emits `photo_tool_response` `{ status: "ok", data: { image: <base64 JPEG> } }`; QR scans use `qr_scan_tool_response`. The exact acknowledgement payload for the photo tool call is still being confirmed.

### C.8 Real-time: AI assistant (raw WebSocket)
| Item | Value |
|---|---|
| URL | `wss://<host>/v2/assistant/live` |
| Auth | §F.2 |
| Query | Same as §C.7, plus `provider` |
| Frames | JSON text |

Client → server:

| Frame | Meaning |
|---|---|
| `{type:"audio", data}` | base64 PCM16, 16 kHz |
| `{type:"audio_end"}` | Mic paused |
| `{type:"image", data}` | base64 JPEG |
| `{type:"text", text, city?, country?}` | Text input |
| `{type:"reconnect"}` / `{type:"disconnect"}` | Session control |
| `{type:"pong"}` | Heartbeat reply |
| `{type:"tool_result", callId, result, isError?}` | Tool answer |

Server → client:

| Frame | Meaning |
|---|---|
| `{type:"connected", sessionId, resumeKey}` | Session ready |
| `{type:"audio", data}` | base64 PCM16 |
| `{type:"audio_transcript", text}` / `{type:"input_transcript", text}` | Transcripts |
| `{type:"tool_call", callId, name, args}` | Tool request |
| `{type:"interrupted"}` / `{type:"turn_complete"}` | Turn state |
| `{type:"ping"}` | Heartbeat; reply `pong` |
| `{type:"error", message, code?, retryAfterMs?}` | Failure |

Close codes: `4401` unauthenticated, `4500` service not configured or connect failed, `4503` server shutting down.

### C.9 Real-time: live translation (raw WebSocket)
| Item | Value |
|---|---|
| URL | `wss://<host>/v2/translation/live?source_lang=&target_lang=&speak=&timezone=&device_mac=` |
| Auth | §F.2 |
| Defaults | `source_lang` = `auto`, `target_lang` = `en`; speech on unless `speak=off` |
| Frames | **JSON text only** |
| Heartbeat | Server sends `ping` every **20 s**; reply `{type:"pong"}`. The session is closed after **90 s** without a pong |
| Close codes | `4401` unauthenticated, `4500` not configured / switched off / start failed, `4503` shutting down or too many active sessions |

Client → server:

| Frame | Meaning |
|---|---|
| `{type:"audio", data}` | base64 **PCM16, 16 kHz, mono** |
| `{type:"audio_end"}` | Mic paused; finish the current sentence |
| `{type:"pong"}` | Heartbeat reply |
| `{type:"speak", enabled}` | Turn spoken translation on/off mid-session |
| `{type:"playback", queuedMs}` | Optional: ms of speech queued on the device |
| `{type:"disconnect"}` | User stopped translation |

Server → client:

| Frame | Meaning |
|---|---|
| `{type:"connected", sessionId}` | Session ready |
| `{type:"partial", sentenceId, text, sourceText}` | Interim result |
| `{type:"final", sentenceId, text, sourceText, detectedLanguage?}` | Final result |
| `{type:"playing_started", sentenceId}` / `{type:"playing_finished", sentenceId}` | Speech playback window |
| `{type:"audio", sentenceId, data}` | Spoken translation: base64 **PCM16, 24 kHz, mono** |
| `{type:"ping"}` | Heartbeat |
| `{type:"error", message, code?, retryAfterMs?}` | `code`: `service_error`, `config_error`, `rate_limited` |

---

## D. Request/Response Models

### D.1 Conventions
- REST request and response fields are **camelCase**.
- WebSocket and Socket.IO query params are **snake_case**.
- Ids are **UUID strings**.
- Timestamps are ISO-8601 strings.

### D.2 User and session (`GET /v2/auth/get-session`)
```json
{
  "session": { "id": "uuid", "userId": "uuid", "expiresAt": "ISO-8601", "activeOrganizationId": "uuid | null" },
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "...",
    "emailVerified": true,
    "role": null,
    "glassUserId": 123,
    "isFirstTimeLogin": false,
    "mustChangePassword": false,
    "canChangePassword": true
  }
}
```
| Field | Meaning |
|---|---|
| `user.id` | Account id (UUID) |
| `user.glassUserId` | Numeric user number the glasses pair with. Every account has one; it's assigned automatically |
| `user.canChangePassword` | `false` for accounts without a usable password (use password reset instead) |
| `user.mustChangePassword` | `true` → every `/v2` call returns `403 AUTH_MUST_CHANGE_PASSWORD` until the password is changed |
| `user.role` | Staff role, or `null` for customers |
| `session.activeOrganizationId` | The current workspace |

The session object shows the main fields; other session and user fields may be present.

### D.3 Device
```json
{
  "id": "uuid",
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "macAddressBt": null,
  "serialNumber": null,
  "modelId": null,
  "modelCode": null,
  "name": null,
  "firmwareVersion": null,
  "os": null,
  "frameVersion": null,
  "status": "provisioned | retired | blocked",
  "boundAt": "ISO-8601",
  "lastSeenAt": null,
  "deviceToken": "17283901 (owner only, otherwise null)"
}
```
- `macAddress` accepts any separator (`:`, `-`, `.`, none) and any case, and is returned as `AA:BB:CC:DD:EE:FF`. Invalid input → `400`.
- `status` is the registry state of the hardware; ownership is expressed by the device appearing in your list.
- `deviceToken` is the device secret the glasses need to reconnect. It's returned only to the owner (bind, get, list, rename).

### D.4 Client headers
| Header | Required | Purpose |
|---|---|---|
| `Authorization: Bearer <token>` | Native clients, protected routes | Session |
| `Content-Type: application/json` | Requests with a body | — |
| `x-install-id` | Recommended on sign-in (mobile) | UUID per install; enables "one phone per account" |
| `x-timezone` | Optional | IANA time zone (e.g. `Asia/Colombo`); display hint for device history and firmware reports |
| `x-client-brand`, `x-client-model`, `x-client-os` | Optional | Phone details for audit history (max 64 chars each) |

---

## E. Error Handling

### E.1 Error envelope
Every error uses one shape:
```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "status": 404,
    "message": "English debug text",
    "details": [ { "field": "macAddress", "code": "custom" } ]
  }
}
```
| Field | Meaning |
|---|---|
| `code` | The stable contract. Branch on it |
| `status` | Always matches the HTTP status |
| `message` | Debugging only. Don't show it to users |
| `details` | Appears on validation errors from `/v2` resource endpoints: field name and failure code, never the submitted value. Validation errors from `/v2/auth/*` (e.g. password policy) have **no** `details` |

Only `/readyz` and `/health` differ: on `503` they return `{ db, status }`.

### E.2 Error codes
| Group | Code | HTTP |
|---|---|---|
| Generic | `VALIDATION_FAILED` | 400 |
| | `UNAUTHENTICATED` | 401 |
| | `FORBIDDEN` | 403 |
| | `NOT_FOUND` | 404 |
| | `CONFLICT` | 409 |
| | `RATE_LIMITED`, `RATE_LIMITED_RETRY_LATER` | 429 |
| | `INTERNAL` | 500 |
| Auth | `AUTH_INVALID_CREDENTIALS` | 401 |
| | `AUTH_EMAIL_NOT_VERIFIED`, `AUTH_MUST_CHANGE_PASSWORD`, `AUTH_ACCOUNT_BANNED`, `AUTH_REAUTH_REQUIRED` | 403 |
| | `AUTH_USER_ALREADY_EXISTS` | 409 |
| | `AUTH_INVALID_TOKEN`, `AUTH_INVALID_OTP`, `AUTH_LAST_SIGN_IN_METHOD`, `AUTH_LINK_EMAIL_MISMATCH`, `AUTH_LINK_FAILED` | 400 |
| Device | `DEVICE_NOT_FOUND`, `DEVICE_NOT_PROVISIONED` | 404 |
| | `DEVICE_NOT_OWNED` | 403 |
| | `DEVICE_ALREADY_OWNED`, `DEVICE_BLOCKED`, `DEVICE_CONTENDED`, `DEVICE_EDIT_BOUND`, `DEVICE_MAC_LOCKED` | 409 |
| | `DEVICE_TOKEN_INVALID` | 422 |
| Account | `ACCOUNT_SOLE_OWNER` | 409 |
| | `ACCOUNT_DELETED_BY_ADMIN` | 401 |
| Other | `STORAGE_UNAVAILABLE`, `SPORTS_UNAVAILABLE` | 503 |
| | `CONTACTS_SYNC_NOT_CONSENTED` | 403 |

### E.3 Auth situations → code
| Situation | Code |
|---|---|
| Wrong email or password | `AUTH_INVALID_CREDENTIALS` |
| Email not verified | `AUTH_EMAIL_NOT_VERIFIED` |
| Wrong, expired or over-tried code | `AUTH_INVALID_OTP` |
| Invalid or expired link token | `AUTH_INVALID_TOKEN` |
| Email already registered | `AUTH_USER_ALREADY_EXISTS` |
| Session missing or expired | `UNAUTHENTICATED` |
| Recent sign-in required | `AUTH_REAUTH_REQUIRED` |
| Banned account | `AUTH_ACCOUNT_BANNED` |
| Password outside 12–128 chars | `VALIDATION_FAILED` |
| Too many requests | `RATE_LIMITED` (+ `retry-after` header) |

### E.4 Real-time errors
| Channel | Error signal |
|---|---|
| Socket.IO `/live-agent` | `connect_error` on auth failure; `error` event `{ message, code?, retryAfterMs? }` during a session; `session_revoked` when the session ends |
| WebSockets `/v2/*/live` | `{type:"error", ...}` frame during a session; close codes `4401`, `4500`, `4503` |

---

## F. Client Integration

### F.1 Mobile / native apps
1. Sign in (§A.3). Store the token from the **`set-auth-token` header** (or the body `token`).
2. Send `Authorization: Bearer <token>` on every protected call, including the Socket.IO handshake header.
3. Send **`x-install-id: <uuid>`** (one per install, persisted) on sign-in requests.
4. There is **no refresh step**. On `401` (`UNAUTHENTICATED` or `ACCOUNT_DELETED_BY_ADMIN`), send the user to sign-in.
5. On sign-out: `DELETE /v2/me/push-token` **first**, then `POST /v2/auth/sign-out`.
6. Optional: register for push with `PUT /v2/me/push-token`; check `GET /v2/me/device-removals` when the app returns to the foreground.
7. CORS doesn't apply to native apps.

### F.2 WebSocket authentication (`/v2/assistant/live`, `/v2/translation/live`)
In order of preference:
1. **Ticket:** `GET /v2/auth/one-time-token/generate` (signed in) returns a single-use ticket valid for **1 minute**. Connect with `?ticket=<ticket>`.
2. **Header or cookie** on the upgrade request: `Authorization: Bearer <token>` or the session cookie.
3. `?token=<session token>`: **not accepted in production**.

Socket.IO `/live-agent` accepts only the `authorization` header.

### F.3 Web / browser apps
- Cookie-based. Send requests with **`credentials: "include"`**.
- Only allowlisted origins get credentialed CORS responses. Contact the API team to have a web origin added. Requests from other origins get no `Access-Control-Allow-Origin`.
- Allowed request headers: `Content-Type`, `Authorization`, `x-request-time`, `x-device-id`, `x-timezone`, `x-event-name`, `x-action`, `x-client-brand`, `x-client-model`, `x-client-os`.
- Allowed methods: GET, POST, PUT, PATCH, DELETE, OPTIONS. Preflight cache: 600 s.
- `callbackURL` / `redirectTo` values sent to `/v2/auth/*` must be trusted origins, otherwise `403`.

---

## G. Important Implementation Details

| Topic | Behavior |
|---|---|
| Session store | Sessions live on the server. Deleting one invalidates its cookie and bearer token immediately; there is no grace period |
| One phone per account | Applies only when `x-install-id` is sent. The newest phone always survives; two phones signing in at the same moment don't sign each other out |
| Password reset | Ends every session of the account |
| Account deletion | Ends every session and releases all glasses immediately. Glasses aren't re-bound if the deletion is cancelled |
| Safe retries | `bind` on your own device and `unbind` on a released device are idempotent; no idempotency header is needed |
| Device ownership | Always taken from the session. Ids in request bodies are never used as the owner |
| Firmware download | The `url` from the firmware check expires after 15 minutes. Call check again for a fresh link |
| Firmware report | Sent once at the end. A check with no matching report shows up as an install that never finished |
| Validation | Unknown or malformed values return `400 VALIDATION_FAILED`, with `details` on `/v2` resource endpoints and without on `/v2/auth/*`; submitted values are never echoed |
| Live sessions on deploy | During shutdown the server stops accepting live sessions (`4503`) and hands over active ones; clients should reconnect, using `resume_key` for the assistant |
| Socket.IO heartbeat | Socket.IO's own heartbeat is used; no `ping` events are emitted on `/live-agent` |

---

## H. Per-Environment Items
These depend on the deployment. Confirm them for each environment:
- Host names for REST, WebSocket and Socket.IO.
- The session cookie domain (parent domain or host-only).
- The app deep-link scheme used by magic-link emails.
- The list of allowlisted web origins.
- Whether staff two-factor authentication is enforced.
- The maximum number of concurrent live-translation sessions.
- Full response schemas for every endpoint, from `GET /openapi.json` on that environment.
