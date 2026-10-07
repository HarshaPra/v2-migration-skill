# API V1 Endpoint Reference

## 1. Base URL

```
https://<host>/api/v1
```

- All paths below are relative to `/api/v1`.
- Request and response bodies are JSON (`Content-Type: application/json`) unless stated otherwise.

---

## 2. Authentication Mechanism

| Item | Behavior |
|---|---|
| Token type | JWT access token + refresh token, issued by the auth endpoints below |
| How to send | `Authorization: Bearer <access_token>` header |
| Cookies | Not used |
| Validation | Checked on every protected request; an invalid, expired or missing token returns `401` |
| Expiry | The response includes `expiresIn` (seconds) and `expiresAt` (unix seconds) |
| Refresh | `POST /auth/refresh` with the refresh token. Each refresh returns a **new refresh token**; the old one should not be reused |
| Public endpoints | Marked **Public** below; no token needed |

### 401 response
```json
{ "statusCode": 401, "message": "Unauthorized" }
```
Missing header: `"message": "No authorization header provided"`.

---

## 3. Auth Endpoints

### POST `/auth/signup` (Public)
Register with email and password. The email must be verified before sign-in.

Request:
```json
{ "email": "user@example.com", "password": "min 8 chars", "displayName": "min 2 chars", "phone": "+1234567890 (optional)" }
```
Response `200`:
```json
{ "user": { "message": "Registration successful. ...", "email": "user@example.com" } }
```
Errors: `400` validation, `409` email already registered.

### POST `/auth/signin` (Public)
Request:
```json
{ "email": "user@example.com", "password": "********" }
```
Response `200`:
```json
{
  "user": {
    "session": {
      "accessToken": "jwt",
      "refreshToken": "token",
      "expiresIn": 3600,
      "expiresAt": 1760000000,
      "token_type": "bearer",
      "email": "user@example.com",
      "user_id": "uuid",
      "user_role": "User"
    },
    "profile": { "id": 123, "auth_id": "uuid", "name": "...", "email": "...", "active": true, "img": null, "bg_image": null, "birthday": null, "height": null, "weight": null, "gender": null, "created_at": "...", "user_role": { "id": 1, "role_name": "User" } },
    "subscription": null
  }
}
```
Errors:

| Status | Reason |
|---|---|
| `401` | Invalid credentials |
| `403` | Account inactive, email not confirmed, or temporary password expired |
| `404` | Profile not found |

### POST `/auth/signin-oauth` (Public)
Sign in or register with Google or Apple. Creates the account if it doesn't exist.

Request:
```json
{ "provider": "google | apple", "idToken": "provider JWT", "nonce": "raw nonce (Apple)" }
```
Response `200`: a session object at the top level:
```json
{
  "access_token": "jwt",
  "refresh_token": "token",
  "expires_in": 3600,
  "expires_at": 1760000000,
  "token_type": "bearer",
  "user": { "id": "uuid", "email": "...", "user_metadata": { "full_name": "...", "avatar_url": "..." } }
}
```
Errors: `400` validation, `401` invalid provider token.

### POST `/auth/refresh` (Public)
Request (the refresh token goes in the `code` field):
```json
{ "code": "<refresh_token>" }
```
Response `200`:
```json
{
  "user": { "id": "uuid", "email": "..." },
  "session": { "access_token": "jwt", "refresh_token": "new token", "expires_in": 3600, "expires_at": 1760000000, "token_type": "bearer" }
}
```
Errors: `400` missing code, `401` invalid or expired refresh token.

### POST `/auth/signout` (Bearer)
No body. Response `200`: `{ "user": { ... } }`.

- The server does not revoke the caller's access token.
- The client must discard its stored tokens.

### POST `/auth/send-otp` (Public)
Sends a one-time code to the email. Creates the account if it doesn't exist.

Request: `{ "email": "user@example.com" }`
Response `200`: `{ "message": "A one-time password has been sent to ..." }`

### POST `/auth/verify-otp` (Public)
Request:
```json
{ "email": "user@example.com", "token": "123456", "type": "signup | invite | magiclink | recovery | email_change | email" }
```
Response `200`: a message plus the session fields at the top level:
```json
{ "message": "OTP verified successfully. You are now signed in.", "access_token": "jwt", "refresh_token": "token", "expires_in": 3600, "expires_at": 1760000000, "token_type": "bearer", "user": { ... } }
```
Errors: `401` invalid or expired OTP.

Which `type` to use:

| Flow | `type` |
|---|---|
| Sign-up verification | `signup` |
| Email code login | `magiclink` or `email` |
| Password recovery | `recovery` |

### POST `/auth/resend-verification` (Public)
Request: `{ "email": "user@example.com" }`
Response `200`: `{ "message": "Verification email resent. Please check your inbox." }`

### POST `/auth/reset-password` (Public)
Sends a password-reset email.

Request: `{ "email": "user@example.com" }`
Response `200`: `{ "message": "If an account with that email exists and is verified, ..." }`
Errors: `403` email not confirmed.

### POST `/auth/update-password` (Bearer)
Sets a new password for the user identified by the Bearer token. For password recovery, use the access token returned by `verify-otp` with `type: recovery`.

Request:
```json
{ "password": "min 8 chars" }
```
- The optional `refresh_token` field is accepted but not used.

Response `200`: `{ "message": "Password updated successfully." }`
Errors: `401` invalid token.

### POST `/auth/change-email/request` (Bearer)
Step 1. Sends a 6-digit code to the new email.

Request:
```json
{ "newEmail": "new@example.com", "refreshToken": "<current refresh token>" }
```
Response `200`: `{ "message": "Verification code sent to new email address", "newEmail": "new@example.com" }`
Errors: `400` same as the current email, `409` email already in use.

### POST `/auth/change-email/verify` (Bearer)
Step 2. Confirms the code.

Request: `{ "token": "123456" }` (exactly 6 characters)
Response `200`: `{ "message": "Email changed successfully", "user": { ... } }`
Errors: `401` invalid or expired code, `409` email taken.

### POST `/auth/delete-account` (Bearer)
Permanently deletes the **caller's** account. The target is always the token owner; any id in the body is ignored. The caller's devices are unbound first.

Response `200`: `{ "message": "User deleted successfully.", "data": { ... } }`
Errors: `409` dependent records block deletion.

---

## 4. Profile

### GET `/user` (Bearer)
Returns the caller's profile **as an array** with one element.

Response `200`:
```json
[ { "id": 123, "auth_id": "uuid", "name": "...", "email": "...", "phone": null, "language": null, "birthday": null, "height": null, "weight": null, "gender": null, "img": null, "bg_image": null, "active": true, "created_at": "..." } ]
```
- Two ids exist:
  - `id`: integer profile id.
  - `auth_id`: the UUID that matches `user_id` / `user.id` in the session.

---

## 5. App Version

### GET `/app-version/check` (Public)
Query:

| Param | Required | Example |
|---|---|---|
| `platform` | yes | `ios` or `android` |
| `version` | no | `1.7.25` |

Response `200`:
```json
{
  "platform": "ios",
  "latestVersion": "1.8.0",
  "minSupportedVersion": "1.6.0",
  "forceUpdate": false,
  "hasUpdate": true,
  "updateMessage": "...",
  "storeUrl": "https://apps.apple.com/app/id6642646426",
  "releaseNote": "..."
}
```
- `forceUpdate` is true when `version` < `minSupportedVersion`.
- `hasUpdate` is true when `version` < `latestVersion`.
- Both are `null` if `version` is missing or can't be parsed.

Errors: `400` invalid platform, `404` no active version config for the platform. Treat `404` as "no update".

---

## 6. Firmware

### GET `/firmware/latest/{deviceType}` (Bearer)
- Path: `deviceType` is a decimal number, for example `6`.
- Query: `currentVersion` (optional), for example `1.7.23`.

Response `200`, update available:
```json
{
  "hasUpdate": true,
  "isMandatory": false,
  "message": "New firmware version 1.7.24 is available",
  "firmware": { "id": 42, "version": "1.7.24", "device_type": 6, "releasenotes": "...", "sha256": "...", "is_mandatory": false, "created_at": "..." }
}
```
Response `200`, no update:
```json
{ "hasUpdate": false, "message": "Your firmware is up to date" }
```
- A non-numeric `deviceType` returns the "no update" response.
- Errors: `404` no firmware for the device type.

### GET `/firmware/download/{firmwareId}` (Bearer)
Response `200`:
```json
{ "download_url": "https://... (temporary signed URL)" }
```
Errors: `404` not found.

### POST `/firmware/update-log` (Bearer)
Creates an update-log entry when an OTA update starts. The user is taken from the token.

Request (all fields optional):
```json
{ "macId": "AA:BB:CC:DD:EE:FF", "oldFirmwareVersion": "1.7.23", "newFirmwareVersion": "1.7.24", "startTime": "2026-10-07T10:00:00Z" }
```
Response `201`: `{ "id": 987 }`

### PATCH `/firmware/update-log/{id}` (Bearer)
Records the outcome.

Request:
```json
{ "endTime": "2026-10-07T10:05:00Z", "status": "success | failed | cancelled | interrupted", "failureReason": "optional text" }
```
Response `200`: `{ "id": 987 }`
Errors: `404` log not found.

---

## 7. Device Binding (Terminals)

### Flow
```
verify  ──►  (device handshake using cloud_token)  ──►  bind
                                                         │
me/terminals (on launch)   rename   unbind  ◄────────────┘
```

### Mechanisms
| Mechanism | Behavior |
|---|---|
| `cloud_token` | Short-lived signed token returned by `verify`. Default TTL is **90 seconds**. Must be sent to `bind` for the same user and `mac_ble` |
| `Idempotency-Key` header | **Required** on `bind` and `unbind`. 1–128 chars of `A–Z a–z 0–9 _ - : .` |
| Idempotent replay | The same key with the same body returns the cached 2xx response. The same key with a different body returns `422 IDEMPOTENCY_MISMATCH`. Errors are not cached, so retrying with the same key is safe |
| `device_token` | Device secret. Returned only to the device's current owner |
| Field naming | snake_case in requests and responses |

### Terminal object
```json
{
  "id": 42,
  "mac_ble": "AA:BB:CC:DD:EE:FF",
  "mac_bt": "AA:BB:CC:DD:EE:00",
  "model": "0215000A",
  "name": "MyGlass A1B2",
  "firmware_ver": "1.7.23",
  "serial": "MGG02X12261000001",
  "bound_at": "2026-10-07T10:00:00Z",
  "status": "active | unbound | force_released | archived | disputed_revoked",
  "device_token": "17283901 or null"
}
```

### POST `/terminals/verify` (Bearer)
Request:
```json
{ "mac_ble": "AA:BB:CC:DD:EE:FF", "model": "0215000A", "observed_device_token": "optional", "firmware_ver": "optional", "reset_nonce": "optional, ignored" }
```
Response `200`:
```json
{
  "state": "available | owned_by_you | owned_by_other | release_directive | reserved_by_other",
  "cloud_token": "base64url",
  "cloud_token_ble": 123456789,
  "expires_at": "2026-10-07T10:01:30Z",
  "ttl_seconds": 90,
  "device_token": "only when owned_by_you",
  "claim_after_reset_allowed": true,
  "terminal": { /* Terminal object */ }
}
```
- `release_directive` returns only `state` and `terminal`. It means the device thinks it's bound, but it isn't.
- `claim_after_reset_allowed` appears only for `owned_by_other`.

### POST `/terminals/bind` (Bearer + `Idempotency-Key`)
The body is strict: unknown fields are rejected.

```json
{
  "mac_ble": "AA:BB:CC:DD:EE:FF",
  "mac_bt": "AA:BB:CC:DD:EE:00",
  "model": "0215000A",
  "name": "MyGlass",
  "cloud_token": "from verify",
  "device_token": "numeric string from device handshake",
  "firmware_ver": "optional",
  "serial": "optional",
  "device_type": "optional, digits only",
  "frame_version": "optional, digits only",
  "os": "optional, digits only",
  "request_configuration_sn": "optional",
  "claim": false
}
```
- `claim: true` only when claiming a factory-reset device that is currently bound to another account.

Response `200`: `{ "terminal": { /* Terminal object with device_token */ } }`

### POST `/terminals/{id}/unbind` (Bearer + `Idempotency-Key`)
The body is strict:
```json
{ "reason": "user_initiated | phone_reset | support_unbind (free text, 1-256)" }
```
Response `200`: `{ "terminal": { ... } }`, or `{}` if the device was already unbound.

### POST `/terminals/{id}/name` (Bearer)
The body is strict:
```json
{ "name": "MyGlass A1B2" }
```
- The name is trimmed and must be 1–64 characters.
- Control and invisible formatting characters are rejected.

Response `200`: `{ "terminal": { ... } }`

### GET `/me/terminals` (Bearer)
Lists the caller's active devices.

Response `200`:
```json
{ "terminals": [ { /* Terminal object with device_token */ } ] }
```

### Terminal error format
```json
{ "code": "OWNED_BY_OTHER", "message": "..." }
```
| Code | HTTP | Meaning / action |
|---|---|---|
| `INVALID_REQUEST` | 400 | Body validation failed |
| `INVALID_CLOUD_TOKEN` | 400 | Tampered or malformed `cloud_token` |
| `INVALID_CLAIM_TOKEN` | 400 | Invalid claim |
| `UNSUPPORTED_MODEL` | 400 | Model not supported |
| `MISSING_IDEMPOTENCY_KEY` | 400 | Header missing or malformed |
| `UNAUTHENTICATED` | 401 | No user |
| `FORBIDDEN` | 403 | Caller doesn't own the device |
| `DEVICE_NOT_PROVISIONED` | 404 | MAC not in the device whitelist |
| `NOT_FOUND` | 404 | Unknown device id |
| `OWNED_BY_OTHER` | 409 | Bound to another account; use `claim: true` after a factory reset |
| `RESERVED_BY_OTHER` | 409 | Reserved by another user |
| `DEVICE_UNAVAILABLE` | 409 | Archived or revoked |
| `CLOUD_TOKEN_EXPIRED` | 410 | Call `verify` again |
| `DEVICE_TOKEN_INVALID` | 422 | `device_token` invalid |
| `IDEMPOTENCY_MISMATCH` | 422 | Same key with a different body |
| `CLAIM_RATE_LIMITED` | 429 | Too many claim attempts for this MAC |

---

## 8. Real-time Agent (Socket.IO)

| Item | Value |
|---|---|
| Protocol | Socket.IO |
| URL | `https://<host>` with namespace `/live-agent` (no `/api/v1` prefix) |
| Auth | Handshake header `Authorization: Bearer <access_token>` |
| Auth check | Only at connect. An invalid token disconnects the socket with no error event. Reconnect with a fresh token after a refresh |

### Handshake query params
| Param | Example |
|---|---|
| `device_type` | `ultra` |
| `firmware_version` | `1.7.23` |
| `timezone` | `Asia/Colombo` |
| `city`, `country` | `Colombo`, `Sri Lanka` |
| `current_date` | `2026-10-07` |
| `current_time` | `10:15:00 AM` |
| `sessionType` | `audio` (default) |
| `macId` | device MAC (optional) |

### Client → server events
| Event | Payload |
|---|---|
| `audio_stream` | base64 PCM audio string |
| `video_stream` | base64 frame |
| `analyze_image` | `{ image: base64, message: string }` (only these two fields are read; missing `image` emits `error`) |
| `stop_agent` | none |
| `message` | text; echoed back only |

### Server → client events
| Event | Meaning |
|---|---|
| `gemini_session_opened` | Session ready |
| `gemini_audio` | Audio response chunk |
| `gemini_response` / `gemini_text_response` | Text response |
| `gemini_input_transcript` / `gemini_output_transcript` | `{ text }` transcripts |
| `gemini_turn_complete` | Turn finished |
| `gemini_interrupted` | Stop playback |
| `gemini_request_lost` | Request dropped |
| `gemini_error` / `error` | `{ message }` |
| `dual_session_error` | Session conflict |
| `device_tool_call` | `{ tool, args }`. The client must ack with the result or `{ status: "error", error }` |
| `session_refreshing`, `session_refreshed`, `session_resumed`, `gemini_reconnecting`, `gemini_reconnected`, `gemini_reconnection_failed`, `session_reconnect_needed` | Session lifecycle |
| `agent_stopped` | Agent stopped |
| `tool_call_started` / `tool_call_ended` | Tool lifecycle |

---

## 9. Live Translation (WebSocket)

Live translation runs on a **separate host**, not on `/api/v1`. It uses a plain WebSocket, not Socket.IO.

### Connection
| Item | Value |
|---|---|
| URL | `wss://thinkar-dev-ai-agent.azurewebsites.net/ws/translate_v2` (dev host) |
| Protocol | Raw WebSocket (RFC 6455) |
| Auth | Same access token as the API, passed as **query param** `auth_token` (URL-encoded). No `Authorization` header |
| Max message size | 16 MB |

```
wss://<translation-host>/ws/translate_v2?source_lang=<code>&target_lang=<code>&auth_token=<access_token>
```

### Query params
| Param | Required | Meaning | Example |
|---|---|---|---|
| `source_lang` | yes | Language being spoken (glasses wearer) | `en` |
| `target_lang` | yes | Language to translate into | `ja` |
| `auth_token` | yes | Access token from sign-in / refresh | `eyJ...` |

**Language codes:** mostly BCP-47 or ISO codes.

| Language | Code sent |
|---|---|
| Simplified Chinese | `zh-CN` |
| Traditional Chinese | `zh-TW` |
| Portuguese, all variants | `pt` |
| Latin American Spanish | `es` |
| British English | `en` |
| All others | the code as-is |

For these languages translation is **text-only, with no audio**: `ha`, `yo`, `ig`, `tt`, `mai`, `ku`, `xh`, `ht`, `mg`, `rw`, `sn`, `sm`.

### Client → server
| Frame | Content |
|---|---|
| Binary | Continuous audio stream: **PCM Float32 little-endian, 16 kHz, mono** |
| Text | Heartbeat `{"type":"ping"}` every **25 s** |
| Text | `{"type":"pong"}` in reply to a server `{"type":"ping"}` |

### Server → client
| Frame | Content |
|---|---|
| Text (JSON) | Translation result (below) |
| Text (JSON) | `{"type":"ping"}` / `{"type":"pong"}` heartbeat |
| Binary | Synthesized speech (TTS) audio for the translation. Not sent for the text-only languages above |

Translation result:
```json
{ "source_text": "recognized speech in source_lang", "translation": "translated text in target_lang", "complete": false }
```
| Field | Notes |
|---|---|
| `source_text` | Recognized speech |
| `translation` | Translated text. Some messages use `text` instead of `translation` |
| `complete` | `false` = interim, still being spoken; `true` = final, utterance finished. May arrive as a boolean or as the string `"true"` / `"false"` |

### Session mechanisms
| Mechanism | Behavior |
|---|---|
| One direction per socket | Each connection translates `source_lang` → `target_lang` only. To swap the direction, open a new connection with the params reversed |
| Keep-alive | Application-level JSON ping/pong every 25 s |
| Reconnect | On receive failure, open a **new** socket. Up to 3 attempts with backoff 2 s, 4 s, 8 s (max 10 s) |
| Token | Sent only in the connect URL; nothing re-sends it during the session. To use a refreshed token, reconnect with the new `auth_token` |
| Stop | Close the socket with code `1001` (going away) |

---

## 10. General Error Format

| Case | Body |
|---|---|
| Standard error | `{ "statusCode": 400, "message": "...", "error": "Bad Request" }` |
| Validation error (auth, user, app version) | `{ "statusCode": 400, "message": "Validation failed", "errors": [ { "path": ["email"], "message": "Invalid email address", ... } ] }` (`path` is an array) |
| Validation error (device, firmware) | `{ "message": "Validation failed", "errors": [ { "path": "<field>", "message": "...", "metadata": "body" } ] }` (`path` is a string) |
| Terminal endpoints | `{ "code": "...", "message": "..." }` (§7) |

---

## 11. Endpoint Summary

| Method | URL | Auth | Extra headers |
|---|---|---|---|
| POST | `/api/v1/auth/signup` | Public | |
| POST | `/api/v1/auth/signin` | Public | |
| POST | `/api/v1/auth/signin-oauth` | Public | |
| POST | `/api/v1/auth/refresh` | Public | |
| POST | `/api/v1/auth/signout` | Bearer | |
| POST | `/api/v1/auth/send-otp` | Public | |
| POST | `/api/v1/auth/verify-otp` | Public | |
| POST | `/api/v1/auth/resend-verification` | Public | |
| POST | `/api/v1/auth/reset-password` | Public | |
| POST | `/api/v1/auth/update-password` | Bearer | |
| POST | `/api/v1/auth/change-email/request` | Bearer | |
| POST | `/api/v1/auth/change-email/verify` | Bearer | |
| POST | `/api/v1/auth/delete-account` | Bearer | |
| GET | `/api/v1/user` | Bearer | |
| GET | `/api/v1/app-version/check` | Public | |
| GET | `/api/v1/firmware/latest/{deviceType}` | Bearer | |
| GET | `/api/v1/firmware/download/{firmwareId}` | Bearer | |
| POST | `/api/v1/firmware/update-log` | Bearer | |
| PATCH | `/api/v1/firmware/update-log/{id}` | Bearer | |
| POST | `/api/v1/terminals/verify` | Bearer | |
| POST | `/api/v1/terminals/bind` | Bearer | `Idempotency-Key` |
| POST | `/api/v1/terminals/{id}/unbind` | Bearer | `Idempotency-Key` |
| POST | `/api/v1/terminals/{id}/name` | Bearer | |
| GET | `/api/v1/me/terminals` | Bearer | |
| WS | `/live-agent` (Socket.IO) | Bearer (handshake header) | |
| WSS | `wss://<translation-host>/ws/translate_v2?source_lang=&target_lang=&auth_token=` | `auth_token` query param | |
