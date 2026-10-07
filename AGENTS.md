<!-- Generated from SKILL.md — edit SKILL.md, then regenerate (see README.md). -->
# ThinkAR API V1 → V2 Migration

You are migrating a **client application** from ThinkAR API V1 to API V2. Follow these rules exactly. The facts below were verified against both API implementations. **Do not guess beyond them.**

> **Paths:** `references/...` below means the `references/` folder of this skill. If you installed the skill into a project as `v2-migration-skill/`, read them at `v2-migration-skill/references/...`.

## Reference documents (read these before changing code)
| File | Use it for |
|---|---|
| `references/api-v1-to-v2-migration-guide.md` | **Primary source.** Endpoint mapping, before/after request and response examples, errors, client steps, checklist, troubleshooting |
| `references/v1-to-v2-migration-analysis.md` | Field-by-field request/response diffs, breaking changes, the "Needs manual review" list |
| `references/v2-technical-inventory.md` | V2 behavior only: auth, every endpoint, models, errors, WebSocket protocols |
| `references/v1-api-endpoints.md` | V1 behavior only: what the old code was calling |

If two documents ever disagree, the **migration guide** wins. Then report the conflict to the user.

---

## 1. Hard rules

1. **Never invent a mapping.** If a V1 call, field, event or state isn't in the references, don't map it. Mark it `TODO(v2-migration): needs manual review — <reason>` and list it in your final report.
2. **Don't implement the open items** (§7). Leave a `TODO(v2-migration)` and report it.
3. **Migrate auth first.** Every other V2 call depends on the session token.
4. **One credential model per client.** Don't let V1 tokens and V2 tokens coexist in the same request path. Delete V1 token storage once V2 auth works.
5. **Don't add a refresh flow.** V2 has no refresh token and no refresh endpoint. Remove all V1 refresh code and expiry timers.
6. **Never use the JWT from `GET /v2/auth/token`** as a credential. `/v2` endpoints only accept the session token.
7. **Mobile and API clients keep `Authorization: Bearer`.** Only browsers switch to cookies. Don't move a native app to cookies.
8. **Ids become strings.** User, device and firmware-release ids are UUID strings. Change model types, persistence and comparisons. The glasses' numeric user id is `user.glassUserId`.
9. **Use camelCase in V2 REST bodies.** WebSocket and Socket.IO query params stay snake_case.
10. **Parse errors only from `error.code`.** Never branch on `message`.
11. **Keep the current behavior unless the V2 contract forces a change.** Don't refactor unrelated code.
12. **Never put secrets in code or logs.** That includes session tokens, one-time tickets and push tokens.
13. **Ask before destructive or ambiguous changes**, for example deleting a feature that has no V2 equivalent.

---

## 2. Workflow

### Step 1: Find every V1 touchpoint
Search the codebase for these patterns, and list every hit with its file and line:

```
/api/v1            auth/signin       auth/signup        auth/refresh       refreshToken
refresh_token      expiresAt         auth/signout       send-otp           verify-otp
resend-verification  reset-password  update-password    change-email       delete-account
signin-oauth       /user             app-version        firmware/latest    firmware/download
update-log         terminals         me/terminals       Idempotency-Key    cloud_token
cloud_token_ble    claim             mac_ble            device_token       firmware_ver
/live-agent        analyze_image     video_stream       stop_agent         macId
translate_v2       auth_token        source_text        thinkar-dev-ai-agent
```
Also find: the base-URL constants, the auth header builder, token storage, the error parser, and every model with integer `id` fields for users, devices or firmware.

### Step 2: Map each touchpoint
- Use the endpoint matrix in §4 below, then confirm the details in `references/api-v1-to-v2-migration-guide.md` §5–§7.
- Classify each one: Renamed, Changed, Replaced, Removed, New, or **Needs manual review**.

### Step 3: Migrate, in this order
1. Configuration: base URLs (§3.1).
2. Authentication: sign-in, token storage, headers, sign-out, 401 handling (§3).
3. The error parser (§5).
4. User / profile.
5. Devices.
6. Firmware.
7. App update check.
8. Live agent (Socket.IO).
9. Live translation (WebSocket).
10. Optional V2 features (push token, device removals): only if the user asks.

### Step 4: Verify
- Update or add tests for every changed call.
- Run the project's build, lint and tests. Fix anything you broke.
- Walk through the checklist in `references/api-v1-to-v2-migration-guide.md` §10.

### Step 5: Report
End with the report format in §8.

---

## 3. Authentication (the most important part)

### 3.1 Base URLs
| What | V1 | V2 |
|---|---|---|
| REST | `https://<host>/api/v1` | `https://<host>/v2` |
| Socket.IO (live agent) | `https://<host>` + `/live-agent` | `https://<host>` + `/live-agent` (path `/socket.io/`, not under `/v2`) |
| Live translation | `wss://<translation-host>/ws/translate_v2` (separate host) | `wss://<host>/v2/translation/live` (API host) |

Keep each base URL in **one** place. Remove the separate translation host.

### 3.2 Sign-in
| Flow | V2 call | Body |
|---|---|---|
| Email + password | `POST /v2/auth/sign-in/email` | `{ email, password, rememberMe? }` |
| Google / Apple | `POST /v2/auth/sign-in/social` | `{ provider, idToken: { token, nonce? } }`. **`idToken` is an object now** |
| Email code | `POST /v2/auth/email-otp/send-verification-otp` `{ email, type: "sign-in" }`, then `POST /v2/auth/sign-in/email-otp` `{ email, otp }` | Creates the account if none exists |
| Sign-up | `POST /v2/auth/sign-up/email` `{ email, password, name }` → `{ token: null, user }` | `token: null` is **expected**; it is not an error |
| Verify sign-up code | `POST /v2/auth/email-otp/verify-email` `{ email, otp }` → `{ status, token, user }` | Signs the user in |

Rules for all sign-in calls:
- **Token:** read the session token from the `set-auth-token` **response header** or the body `token`. They're **different strings** (signed vs plain); both are valid as Bearer. **Store exactly one** in secure storage and use only that one.
- **`x-install-id` (mobile):** send it on **every** call that creates a session. It's a UUID generated once per install and persisted. This turns on "one phone per account": a newer phone signing in signs the older phones out.
- **Passwords:** 12–128 characters. Update client-side validation.
- **Sign-in response fields:** the V1 fields `accessToken`, `refreshToken`, `expiresIn`, `expiresAt`, `profile`, `user_role` and `subscription` no longer exist. Read the user from `GET /v2/me` or `GET /v2/auth/get-session`.

### 3.3 Authenticated requests
| Client | How |
|---|---|
| Mobile / API | `Authorization: Bearer <session token>` |
| Browser | No header. Send `credentials: "include"`; the `HttpOnly` cookie carries the session. The origin must be on the V2 allowlist |

### 3.4 Sign-out (order matters)
1. `DELETE /v2/me/push-token` `{ token }`: **first**, if push is registered. After sign-out it returns `401` and the phone keeps receiving pushes.
2. `POST /v2/auth/sign-out` → `{ success: true }`. The session is deleted on the server.
3. Clear local state.

### 3.5 Session expiry and 401 handling
- Sessions last 7 days and renew automatically with use. There is **no refresh**.
- The server can end a session at any time: sign-out, a password reset (ends **all** sessions), account deletion, or a newer phone signing in.

| Response | Handling |
|---|---|
| `401` (`UNAUTHENTICATED`, `ACCOUNT_DELETED_BY_ADMIN`) | Clear the session and go to sign-in |
| `403 AUTH_MUST_CHANGE_PASSWORD` | Go to change password |
| `403 AUTH_REAUTH_REQUIRED` | Ask the user to re-authenticate, then retry |
| `400 AUTH_INVALID_OTP` | Wrong or expired code. **Not a sign-out.** (V1 returned 401 here.) |

### 3.6 Password and email
| V1 | V2 |
|---|---|
| Reset: `reset-password` → `verify-otp(recovery)` → `update-password` + Bearer | `POST /v2/auth/email-otp/request-password-reset` `{ email }`, then `POST /v2/auth/email-otp/reset-password` `{ email, otp, password }` (no Bearer). Or the link flow: `/v2/auth/request-password-reset` + `/v2/auth/reset-password` `{ newPassword, token }` |
| Signed-in password change `{ password }` | `POST /v2/auth/change-password` `{ currentPassword, newPassword, revokeOtherSessions? }` |
| Change email: request + verify code | `POST /v2/auth/change-email` `{ newEmail }` → `{ status: true }`. For a verified account, a confirmation link goes to the **current** email. **Remove the code-entry screen.** It returns success even if the email is already taken |
| `POST /auth/delete-account` | `DELETE /v2/account` `{ password }`. Social-only accounts must have signed in less than 5 minutes ago. Errors: `403 AUTH_REAUTH_REQUIRED`, `409 ACCOUNT_SOLE_OWNER` |

---

## 4. Endpoint matrix (quick reference)

| V1 | V2 | Notes |
|---|---|---|
| `POST /api/v1/auth/signup` | `POST /v2/auth/sign-up/email` | `displayName`→`name`; `phone` removed |
| `POST /api/v1/auth/signin` | `POST /v2/auth/sign-in/email` | |
| `POST /api/v1/auth/signin-oauth` | `POST /v2/auth/sign-in/social` | `idToken` → `{ token, nonce }` |
| `POST /api/v1/auth/refresh` | — | **Remove** |
| `POST /api/v1/auth/signout` | `POST /v2/auth/sign-out` | Push token first (§3.4) |
| `POST /api/v1/auth/send-otp` | `POST /v2/auth/email-otp/send-verification-otp` | Add `type` |
| `POST /api/v1/auth/verify-otp` (signup) | `POST /v2/auth/email-otp/verify-email` | `token`→`otp`; no `type` |
| `POST /api/v1/auth/verify-otp` (magiclink / email) | `POST /v2/auth/sign-in/email-otp` | `token`→`otp` |
| `POST /api/v1/auth/verify-otp` (recovery) | `POST /v2/auth/email-otp/reset-password` | Code + new password together |
| `POST /api/v1/auth/resend-verification` | `POST /v2/auth/email-otp/send-verification-otp` | `type: "email-verification"` |
| `POST /api/v1/auth/reset-password` | `POST /v2/auth/email-otp/request-password-reset` | Or the link flow |
| `POST /api/v1/auth/update-password` | `POST /v2/auth/change-password` (signed in) / reset endpoints (recovery) | |
| `POST /api/v1/auth/change-email/request` | `POST /v2/auth/change-email` | Link-based |
| `POST /api/v1/auth/change-email/verify` | — | Remove |
| `POST /api/v1/auth/delete-account` | `DELETE /v2/account` | |
| `GET /api/v1/user` (array) | `GET /v2/me` `{id, email, name}` / `GET /v2/auth/get-session` | Object, UUID `id`; `glassUserId` in get-session |
| `GET /api/v1/app-version/check?platform&version` | `GET /v2/app-releases/check?platform&build&osVersion` | Response `{ status: up-to-date \| optional \| forced, release, storeUrl }`; never 404 |
| `GET /api/v1/firmware/latest/{deviceType}` | `GET /v2/devices/{id}/firmware/check?currentVersion=` | By device UUID |
| `GET /api/v1/firmware/download/{id}` | — | Use `release.url` (valid 15 min) |
| `POST` + `PATCH /api/v1/firmware/update-log` | `POST /v2/devices/{id}/firmware/updates` | **One** report at the end: `{ releaseId, status, error?, sdkVersion, startedAt, endedAt }` |
| `POST /api/v1/terminals/verify` | `POST /v2/devices/lookup` `{ macAddress }` | No `cloud_token` |
| `POST /api/v1/terminals/bind` | `POST /v2/devices/bind` | camelCase; **no** `Idempotency-Key`, `cloud_token` or `claim` |
| `POST /api/v1/terminals/{id}/unbind` | `POST /v2/devices/{id}/unbind` `{ cause? }` | → `{ released }` |
| `POST /api/v1/terminals/{id}/name` | `POST /v2/devices/{id}/rename` | |
| `GET /api/v1/me/terminals` | `GET /v2/devices?limit&cursor` | `{ devices, nextCursor }` |
| Socket.IO `/live-agent` | Socket.IO `/live-agent` | §6.1 |
| `wss://…/ws/translate_v2` | `wss://<host>/v2/translation/live` | §6.2 |

### 4.1 Device field renames
| V1 | V2 |
|---|---|
| `mac_ble` | `macAddress` |
| `mac_bt` | `macAddressBt` |
| `model` | `modelCode` |
| `device_token` | `deviceToken` |
| `firmware_ver` | `firmwareVersion` |
| `serial` | `serialNumber` |
| `frame_version` | `frameVersion` |
| `bound_at` | `boundAt` |
| `terminal` / `terminals` | (unwrapped device) / `devices` |

- **Device `status`** now means the hardware state (`provisioned | retired | blocked`), **not** the binding. Ownership = the device appears in `GET /v2/devices`.
- **Lookup states:** `available`→`claimable`, `owned_by_you`→`owned_by_me`, `owned_by_other` (unchanged), plus the new states `unregistered`, `blocked`, `retired`.

### 4.2 Other field renames
| V1 | V2 |
|---|---|
| `startTime` | `startedAt` |
| `endTime` | `endedAt` |
| `failureReason` | `error` |
| `releasenotes` | `notes` |
| `is_mandatory` / `isMandatory` | `mandatory` |
| `download_url` | `release.url` |
| `forceUpdate` / `hasUpdate` | `status` |
| `accessToken` / `access_token` | `token` |

---

## 5. Errors

- **V2 format, always:** `{ "error": { "code", "status", "message", "details?" } }`. Replace every V1 error parser with one that reads `error.code`.
- **`details`** (`[{ field, code }]`) appears on `/v2` resource endpoints only. `/v2/auth/*` validation errors have **no** `details` (for example a too-short password → `400 VALIDATION_FAILED`).
- **Device codes:**

  | V1 | V2 |
  |---|---|
  | `OWNED_BY_OTHER` | `409 DEVICE_ALREADY_OWNED` |
  | `DEVICE_UNAVAILABLE` | `409 DEVICE_BLOCKED`, or `404 DEVICE_NOT_PROVISIONED` (retired) |
  | `DEVICE_NOT_PROVISIONED` | unchanged (404) |
  | `DEVICE_TOKEN_INVALID` | unchanged (422) |
  | — | `409 DEVICE_CONTENDED`: retry |
  | `FORBIDDEN` (not your device) | `403 DEVICE_NOT_OWNED` |

- **Removed codes:** `CLOUD_TOKEN_EXPIRED` (410), `INVALID_CLOUD_TOKEN`, `MISSING_IDEMPOTENCY_KEY`, `IDEMPOTENCY_MISMATCH`, `CLAIM_RATE_LIMITED`, `INVALID_CLAIM_TOKEN`. Delete the handlers for them.
- **Unknown device id:** unbind returns `200 { released: false }` (V1: 404); rename returns `403 DEVICE_NOT_OWNED` (V1: 404).
- **Rate limits:** `429 RATE_LIMITED`. Honor the `retry-after` header.
- Full tables: `references/api-v1-to-v2-migration-guide.md` §8.

---

## 6. Real-time

### 6.1 Live agent (Socket.IO `/live-agent`)
- **Auth:** handshake header `authorization: Bearer <V2 session token>`. Only the header is accepted.
- **Query params:**
  - Rename `language`→`app_language` and `macId`→`device_mac`.
  - Keep `device_type`, `firmware_version`, `timezone`, `city`, `country`, `current_date`, `current_time`.
  - Add `platform` and `resume_key`.
  - Drop `sessionType`.
- **Client → server:**
  - Keep `audio_stream` (base64 PCM16 16 kHz) and `message` (string or `{ text, city?, country? }`).
  - Hang up with `close_session`.
  - **Remove** `analyze_image`, `video_stream`, `stop_agent`, `client_ready_to_speak` and `user_interrupt`.
- **Photos:** on `device_tool_call` with `thinkar_device_tool_page_take_AI_photo` / `thinkar_device_tool_page_take_photo`, capture the photo and emit `photo_tool_response` `{ status: "ok", data: { image: <base64 JPEG> } }`. QR scans use `qr_scan_tool_response`. **Ack every `device_tool_call` within 30 s.**
- **Server → client:**
  - Unchanged: `gemini_session_opened` (save `resume_key`), `gemini_audio`, `gemini_output_transcript`, `gemini_input_transcript`, `gemini_turn_complete`, `gemini_interrupted`.
  - `error` replaces `gemini_error`.
  - New: `session_revoked`, which means sign in again.
  - Remove the handlers for events V2 no longer sends (`gemini_response`, `gemini_request_lost`, `dual_session_error`, `connection_error`, …).

### 6.2 Live translation (`wss://<host>/v2/translation/live`)
- **Auth:** an `Authorization` header on the upgrade, the cookie, or `?ticket=<one-time ticket>` from `GET /v2/auth/one-time-token/generate` (single use, 1 minute). **Remove `auth_token`.** `?token=` is rejected in production.
- **Query:** `source_lang` (default `auto`), `target_lang` (default `en`), `speak=off` (optional), `timezone`, `device_mac`.
- **Audio up:** JSON `{"type":"audio","data":"<base64 PCM16, 16 kHz, mono>"}`. **Convert from V1's binary Float32 frames.** Also `audio_end`, `speak {enabled}`, `playback {queuedMs}`, `disconnect`.
- **Heartbeat:** the server sends `{"type":"ping"}` every 20 s. Reply `{"type":"pong"}`; otherwise the session closes after 90 s.
- **Results:** `partial` / `final` `{ sentenceId, text, sourceText, detectedLanguage? }` replace `{ source_text, translation, complete }`. Speech arrives as `audio { sentenceId, data: base64 PCM16 24 kHz }` between `playing_started` and `playing_finished`. Errors: `{type:"error", message, code?, retryAfterMs?}`.
- **Close codes:**

  | Code | Meaning | Action |
  |---|---|---|
  | `4401` | Not authenticated | Re-authenticate |
  | `4500` | Service unavailable / not configured | Show error |
  | `4503` | Server busy or restarting | Reconnect with backoff |

---

## 7. Open items: do NOT implement, leave a TODO and report
These have no confirmed V2 equivalent. If the code depends on one, add `TODO(v2-migration): needs manual review — <item>`, keep the app compiling, and report it:

1. V1 profile fields: `phone`, `birthday`, `height`, `weight`, `gender`, `img`, `bg_image`, `language`.
2. The `subscription` object in the V1 sign-in response.
3. Email-code types `invite` and `email_change`.
4. Glasses handshake values `cloud_token` / `cloud_token_ble` from `terminals/verify`.
5. Lookup states `release_directive`, `reserved_by_other`, and the code `RESERVED_BY_OTHER`.
6. The factory-reset takeover (`claim: true`). V2 refuses to bind a device owned by another account.
7. Bind fields `device_type`, `request_configuration_sn`, and the error `UNSUPPORTED_MODEL`.
8. The exact acknowledgement payload for the photo tool call.
9. LINE sign-in (it uses a redirect flow, not the ID-token call).
10. The step after the change-email confirmation link is clicked.

---

## 8. Final report format
End the migration with:

```
## V1 → V2 migration report

### Changed
- <file>:<line> — <V1 call/field> → <V2 call/field>

### Removed
- <file>:<line> — <what was removed and why (e.g. refresh flow — no V2 equivalent)>

### Needs manual review
- <file>:<line> — <open item # from §7 / unmapped call> — <what the code depended on>

### Verification
- Build: <pass/fail> · Lint: <pass/fail> · Tests: <pass/fail, counts>
- Checklist items not yet verified: <list>
```

## 9. Common mistakes to avoid
- Removing the push token **after** sign-out (it fails with `401`).
- Treating sign-up `token: null` as an error.
- Treating `400 AUTH_INVALID_OTP` as "signed out".
- Storing both the header token and the body token and mixing them.
- Keeping integer ids for devices, users or firmware releases.
- Sending `Idempotency-Key`, `cloud_token` or `claim` to `/v2/devices/bind`.
- Sending the app **version string** to the app update check instead of the integer `build` plus `osVersion`.
- Downloading firmware from a `release.url` older than 15 minutes.
- Sending binary Float32 audio to `/v2/translation/live`.
- Moving a native app to cookies.
- Adding a token-refresh timer.
