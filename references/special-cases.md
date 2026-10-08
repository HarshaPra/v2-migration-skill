# ThinkAR V2: Special Cases

Internal and operations cases that use the normal V2 API in an unusual way. **These are not customer migration steps.** Don't build them into a customer app unless you're asked to.

Each case lists its status, who it's for, the steps, what must be true first, and where the facts come from.

---

## 1. Engineer account updating test glasses' firmware

**Status:** not a blocker; no API change needed. Open question: [1.5](#15-open-question-testing-unreleased-firmware).
**For:** engineer or test accounts that own a set of test glasses. Not customers.
**Checked against:** `thinkar-mono` API source, commit `7c40e4214`, on 2026-10-08.

### 1.1 Why the normal routes work
- One account can own many glasses. Each pair has at most **one** owner: `device_ownership.device_id` is unique (`packages/db/prisma/schema/device-ownership.prisma`).
- The test glasses are only ever bound to the engineer account, so the normal owner routes apply. No special route exists or is needed.

### 1.2 Steps
1. **`POST /v2/devices/bind`** with the glasses' `macAddress`.
   - Makes the engineer account the owner and returns the device, including its `id`.
   - `macAddress` is the only required field. `deviceToken` is optional. Without it, no token is stored for a later Bluetooth reconnect.
   - Binding again from the same account is safe. It counts as a retry: no second owner, and the reported facts are refreshed.
2. **`GET /v2/devices/{id}/firmware/check?currentVersion=…`**
   - Returns `update-available` with the release and its download link (`release.url`, valid 15 minutes), or `up-to-date`.
3. **`POST /v2/devices/{id}/firmware/updates`** to report the result.
   - Send one report at the end: `{ releaseId, status, error?, sdkVersion, startedAt, endedAt }`.

### 1.3 Before using it

| What must be true | Otherwise |
|---|---|
| The glasses are registered by staff (admin devices, `POST /v2/admin/devices`) | Bind returns `404 DEVICE_NOT_PROVISIONED`. Retired glasses return the same error; blocked glasses return `409 DEVICE_BLOCKED` |
| The glasses' model code is linked to a device model. Registering requires `modelCode`; staff link the code under device models | The firmware check returns `status: "unknown-model"` |
| The engineer account owns the glasses (step 1 done) | The firmware check and report return `404 DEVICE_NOT_FOUND` |

- A bind's `modelCode` sets the model only if the glasses have none yet. After that, staff manage it.

### 1.4 Things to watch
- **Customer handover.** Before a pair of test glasses goes to a customer, unbind it, or the customer's bind fails with `409 DEVICE_ALREADY_OWNED` (and the server logs a `rebind_rejected` event). Either way works:
  - the engineer account calls `POST /v2/devices/{id}/unbind`;
  - a staff member with the internal "manage" role calls `POST /v2/admin/devices/{id}/force-unbind`.
- **One phone per account.** A sign-in that sends `x-install-id` signs out the account's other phones. If several engineers share one account on different phones, they sign each other out. Use one account per engineer, or one shared phone.

### 1.5 Open question: testing unreleased firmware
The firmware check gives the engineer account the **same** releases a customer gets:
- only releases marked `otaApplicable`;
- with the same `upgradeScope` and `maxCurrentVersion` limits;
- with no rule based on role or account, and no test or beta channel.

So this route can't deliver firmware that isn't released yet. Marking a release `otaApplicable` offers it to **every** device of that model at once. If engineers need to test firmware before release, ask the API team how. Don't work around it in client code.

**Source:** `apps/api/src/lib/firmware-check.ts`, the `otaApplicable` filter.
