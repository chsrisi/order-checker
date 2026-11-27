# v2 worker switch: decisions

Decision delta for [V2_WORKER_SWITCH_SPEC.md](V2_WORKER_SWITCH_SPEC.md) (SPEC below). Where they
disagree, this file wins, and later rounds win over earlier ones. Code checked at `df70711`.

Status key: ✅ decided · ⚠️ revisit · ❓ open (working default stated) · 📌 kept for later.

## Round 1 (2026-11-27)

### R1.1 Decisions

| Ref | Decision | Status |
|---|---|---|
| W1 | **Both modes**: direct (no password) by default, preselect (the worker types their password) as the alternative. | ✅ |
| W2 | A direct switch needs an **approved (`active`)** device. Password login and login requests keep working on `pending` devices (L1). | ✅ |
| W3 | Device calls are proven with **Keystore key signatures** now, as for login requests. The device token waits for T8.2 (update endpoints). Revisits V2_DELTA Q9. | ✅ ⚠️ Q9 |
| W4 | An assignment waits **10 minutes** for the device, then expires and the console says so. | ✅ |
| W5 | The login screen polls every **5 s** in the foreground, never in the background. | ✅ |
| W6 | A switch **does not move claimed orders**: claims are per worker on purpose. No "reassign claims" action is planned. | ✅ |
| W7 | Revoked is **final**: a recovered scanner is reinstalled (new key, new device). | ✅ |
| W8 | The login screen tells the worker why they were logged out, from the first poll after it. No change to the socket close or the 401. | ✅ |
| W9 | The revoked-device gap is fixed **in T8.1**. | ✅ |

### R1.2 Consequences and corrections to the SPEC

- **Plan written:** IMPLEMENTATION_PLAN step 8, "Worker switch" (T8.1, T8.4a, T8.6, T8.7). The
  rest of T8.4 (`update_now`, `refresh_config`) becomes T8.4b, later. T8.2 now also carries the
  device token that T8.1 used to issue.
- **How W9 is closed** (checked in the code: `auth_service.login_user` knows nothing about the
  device; the app binds the session afterwards through `/v2/device/register`):
  - Revoking a device revokes every session bound to it and closes their sockets, so refresh
    fails at once.
  - `/v2/device/register` from a revoked device **also revokes the calling session** (today it
    only answers 403). A v2 app always registers after a password login, so the session ends
    within one request.
  - An app that never registers is no worse than a v1 app, which never had a device. The device
    key is the trust boundary, and v1 retirement (Q8) closes the rest.
- **The Android app on 403 "Device revoked"** stops retrying and logs out locally, with a
  message on the login screen. It shows "REVOKED" in the device line today and carries on.
- **Audit** stays in the log, like login requests (L2): approve, revoke, device logout,
  assignment created, replaced, expired and collected, each with the admin, device, old worker
  and new worker. No table and no migration.

### R1.3 Open questions

None before planning. P-23–P-27 in the plan are planning defaults you can veto.
