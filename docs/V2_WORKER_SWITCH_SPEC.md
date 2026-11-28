# v2 worker switch from the console (with step 8 brought forward)

Spec (planning flow step 1), 2026-11-27, checked against `df70711` (branch
`feat/v2-worker-list-theme`). No code changes. Background: IMPLEMENTATION_PLAN §5 "next up",
V2_DELTA Delta 13 (step 8 brought forward), V2_SPEC §4A, the login-request spec and delta.
Decisions: [V2_WORKER_SWITCH_DELTA.md](V2_WORKER_SWITCH_DELTA.md) (Round 1, W1–W9 answered), which
wins over this file. Planned as IMPLEMENTATION_PLAN T8.1, T8.4a, T8.6, T8.7.

## 1. Goal

From the console, an admin chooses which worker is logged in on a scanner. The scanner changes
over within seconds, with nobody typing on it. The same machinery gives the console a
**Log out this device** action and real **approve / revoke** for devices: these are the parts of
step 8 that the switch needs.

## 2. What exists today (verified in the code)

| Piece | Code | What it means here |
|---|---|---|
| Device registry | `models.Device`, `queries/devices.py` | `pending` / `active` / `revoked` exist, but **only `pending` is ever written**. Nothing sets `active` or `revoked`, apart from SQL by hand. `token_hash` is unused. |
| Session ↔ device | `AuthSession.device_id`; set by `register_device` (after a password login) and `bind_session_to_device` (login request) | A device's live sessions can be found. Today nothing uses this to revoke. |
| Revocation | `revoke_user_sessions`, `revoke_session`; `conn_mgr.disconnect_user`, `disconnect_session` | Per **worker** ("log out everywhere") and per session. There is **no per-device** revoke. |
| Device proof without a session | `login_request_service._verify`: ECDSA over `oc-login-request:<action>:<subject>:<nonce>`, nonce claimed once in Redis | A logged-out device can already prove who it is with its Keystore key. No device token is needed for that. |
| Admin-approved session | `login_request_service.poll` → `_start_session` → `get_tokens` + `bind_session_to_device` | Issues a session for a worker **without a password**, bound to the device and handed to the key that asked. This is exactly what a switch has to do. |
| Live channel | `/v2/ws`, user-session tickets only | It exists only while a worker is logged in. A logged-out scanner has **no channel**: the console can't reach it. |
| App on revocation | WS close 1008 → next call 401 → `SessionManager.clearLocal` → `AppEvent.LoggedOut` → "Session ended" login screen | A remote logout already works end to end. |
| App while logged out | The login screen polls nothing; the updater checks at start, on resume and every 15 min | A switch to a logged-out scanner needs a new poll (§4.3). |
| Console | Devices page and Dashboard cards (read-only, `online` from live sockets); login requests (T7.12) | Actions go here. |
| Order ownership | `orders.owner_user`, `pick_item_entries.owner_user` | Claims and picks belong to the **worker**, not the device. A switch leaves them with the old worker (§5, W6). |

**Finding (current gap, independent of the switch):** a `revoked` device can still log in with
a password. `/v2/device/register` answers 403 and the app shows "REVOKED", but the session from
`/v2/auth/login` stays valid. Login requests are refused correctly. Real revocation (T8.1) has to
close this.

## 3. How much of step 8 this needs

| Step 8 task | Needed for the switch? | Proposal |
|---|---|---|
| T8.1 approve and revoke | **Yes.** Approve is the trust gate for a direct switch (W2). Revoke must really lock a device out (the finding above). | Bring forward. **Without the device token** (W3). |
| T8.2 device credential on `/v2/client/*` | No | Stays later. |
| T8.3 QR enrollment | No | Stays later. |
| T8.4 device commands | **Partly:** `logout` and `assign_user` | Bring forward as a **desired state that the device polls** (§4.3), not a device WebSocket. `update_now` and `refresh_config` stay later. |
| T8.5 per-device config | No | Stays later. |

## 4. Proposed flow

### 4.1 One mechanism: end the session, then hand over

A switch is always two steps on the server, done together:

1. **End the device's current session**, if there is one: revoke the sessions bound to the
   device and close their sockets. The app goes to its login screen, as with "log out
   everywhere" today, but only on this device and only for this worker.
2. **Leave an assignment for the device:** worker, admin, mode (W1), expiry. The login screen
   picks it up on its next poll and logs in.

This covers both cases: a scanner logged in (its socket closes at once, then the login screen
polls) and one already logged out or switched off (it collects when it next polls, until the
assignment expires). **Log out this device** is step 1 on its own.

### 4.2 The assignment

- Kept in Redis like login requests: one per device, a new one replaces the old one, TTL
  (W4). No migration.
- Mode **direct**: on collection the server issues a session for the worker, bound to the
  device, like an approved login request (`_start_session`). Mode **preselect**: the login
  screen just selects the worker and asks for the password (or "Ask admin to approve").
- Rules carried over from login requests: client-scope workers only, never an admin; a worker
  deleted, or whose password was reset after the assignment, invalidates it; collected once,
  only by the device's own key; a revoked device gets nothing.
- Direct mode needs an **`active`** (approved) device (W2).

### 4.3 The device poll

- `POST /v2/device/state`, signed with the device key like the login-request calls (purpose
  `oc-device:state:<device_id>:<nonce>`). The answer is `{assignment: null}`, or the worker and
  the mode, and in direct mode the token pair, handed over once.
- The app polls **only on the login screen, while it is in the foreground**, every 5 s (W5).
  Logged in, it needs no poll: step 1 closes its socket, and the login screen takes over.
- A poll also refreshes `last_seen_at`. The console can then tell **logged out but reachable**
  from switched off or out of range, which `online` (live socket) can't today.

### 4.4 Console

- **Devices page and Dashboard cards** get actions, depending on the status:
  - `pending`: **Approve**, **Revoke**;
  - `active`: **Switch worker…**, **Log out this device**, **Revoke**;
  - `revoked`: none, or **Restore** (W7).
- **Switch worker…** opens a picker of client workers (search, with the worker currently on
  the device marked). It confirms what happens: "*dina* is logged out on *MT67-2*;
  *eko* is logged in without a password". After that it shows *waiting for the device*
  until the device collects, then the new worker. "Collected" comes as an admin WS frame, like
  `login_requests_update`.
- Revoke asks for a confirmation and says what it does: every session on the device ends, and it
  can't log in or ask again.

### 4.5 Android

- The login screen gets the state poll (§4.3).
  - Direct mode: tokens → the same path as an approved login request (`SessionManager.accept`,
    registration, `enterHome`). A line on the screen says "Logged in by the admin as *eko*".
  - Preselect mode: the picker selects that worker and opens the password step.
- After a step-1 logout, the "Session ended" message names the reason when the server gives one.
  The socket close and the 401 say nothing today (W8).
- Nothing changes for v1: v1 sessions have no `device_id`, so the console can't target a v1
  scanner. Its Devices list only shows v2 devices.

## 5. Rules to hold

- A direct switch means **whoever holds the scanner acts as that worker** (V2_SPEC §4A.4). Every
  switch, logout, approval and revocation is logged with the admin, device, old worker and new
  worker.
- Two admins switching one device at once: the last one wins, and the first sees its
  assignment replaced. Collection is atomic: at most one session.
- A switch never touches the new worker's sessions on **other** devices. A worker can be on two
  scanners, as today.
- The old worker's **claimed orders and picks stay theirs** (ownership is per worker). The new
  worker sees their own claims. Whether a switch should move the claims is W6.
- The device's own key is the only thing that can collect. A captured poll can't be replayed
  (nonce), and an assignment id alone is worthless.
- Operator contract v1 is unchanged. `/v2` grows additively (new device route; v2 snapshot),
  and the admin API grows additively.

## 6. Questions

"When": **before planning** blocks the plan; **before building** can wait for the task.

| Ref | Question | Recommendation | When |
|---|---|---|---|
| W1 | **Direct** switch (no password), **preselect** (the worker types their password), or both? | **Both, direct by default.** Direct is the point of the feature. Preselect costs one extra field, and lets you pick a worker without handing over their account. | before planning |
| W2 | Does a direct switch need an **approved** (`active`) device? | **Yes.** Approval says "this is our scanner", once per device. Login requests and password login keep working on `pending` devices (L1), so approval is not a new hurdle for normal use. | before planning |
| W3 | Q9 chose a **device token** for device calls. The key signatures used by login requests already prove the device without a session. Keep the token for later (T8.2, update endpoints) and use signatures now? | **Yes, signatures now.** They are built, tested and need no storage; `token_hash` stays unused until T8.2. This revisits Q9 (⚠️). | before planning |
| W4 | How long does an assignment wait for a device that is off or out of range? | **10 minutes.** Long enough to walk over and switch the scanner on. After that it expires, and the console says so. | before building |
| W5 | Poll interval on the login screen | **5 s** in the foreground, none in the background. A switch then lands in ≤ 5 s after the logout. | before building |
| W6 | Should a switch hand the old worker's **claimed orders** to the new worker? | **No, not in this feature.** Claims are per worker on purpose. If shift handovers need it, it is a separate "reassign claims" action. | before planning |
| W7 | Can a revoked device be **restored**? | **No.** Revoked is final, as in V2_SPEC §4A.3 (lost or stolen). A recovered scanner is reinstalled: new key, new device. | before building |
| W8 | Tell the worker *why* they were logged out ("switched by the admin to *eko*")? | **Yes, briefly.** The login screen's first poll after a logout returns the reason with the assignment. No contract change to the socket close or the 401. | before building |
| W9 | The revoked-device gap (§2 finding): fix it in this step? | **Yes, in T8.1**: `/v2/auth/login` and refresh refuse a session that would be bound to a revoked device, and revoking ends the sessions already bound. v1 logins are untouched. | before planning |

## 7. Task outline (to plan once W1–W3, W6 and W9 are answered)

1. **Backend, device trust (T8.1 part):** admin approve / revoke endpoints; revoking ends the
   device's sessions and sockets; password login and refresh are refused for revoked devices
   (W9); audit log.
2. **Backend, per-device logout and assignment (T8.4 part):** `POST /admin/devices/{id}/logout`,
   `POST /admin/devices/{id}/assign` (worker, mode), the Redis assignment store, the signed
   `POST /v2/device/state` that collects it, and an admin WS frame on collection. OpenAPI and the
   v2 snapshot grow additively.
3. **Console:** device actions on the Devices page and Dashboard, the worker picker, the waiting
   state, and confirmations.
4. **Android:** the login-screen poll, direct and preselect handling, the logout reason.
5. **Docs:** SYSTEM_REFERENCE (devices, sessions), API, OPERATIONS (new settings, if any), V2_UX
   brief for the console actions and the login-screen line, step 8 rows in the plan.

**Tests:** approve / revoke transitions; a revoked device refused on login, refresh, state and
login requests; per-device logout leaves the worker's other devices alone; an assignment
collected once, only with the device key (bad signature, replayed nonce, another device's key);
expiry; last admin wins; a worker deleted or reset in between; an admin account never
assignable; a `pending` device refused for direct mode (W2); contract v1 unchanged; the
emulator end to end: switch while logged in, switch while logged out, switch while off, then on.
