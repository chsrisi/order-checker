# v2 login request: ask an admin to approve a login

Spec scaffold (planning flow step 1), 2026-11-25, checked against `63ee40b`. Nothing on the server
is implemented. The client shows the button **disabled** ([V2_UX.md](V2_UX.md) §2.7). Decisions are in
[V2_LOGIN_REQUEST_DELTA.md](V2_LOGIN_REQUEST_DELTA.md), which wins over this file.

## 1. Goal

A worker who cannot or does not want to type a password picks their name and taps **Ask admin to
approve**. An admin sees the request in the console, approves or denies it, and on approval the
scanner logs in.

## 2. What exists today

| Piece | Code | Relevance |
|---|---|---|
| Session and tokens | `auth_service.get_tokens(user, ip_address, agent)` | Issues a session without checking a password; an approved request can end here. |
| Device key | `device_service`, `auth.devices` | EC P-256 Keystore key, proves which device asks. Registered only **after** a login; status `pending` until step 8; `revoked` exists. |
| Short-lived state | `ticket_manager` (Redis, GETDEL) | Model for one-use, expiring state. |
| Login throttle | `login_throttle` | Per username, counts failed passwords; says nothing about requests. |
| Name hiding | F-M17, dummy Argon2 verify | A request must not reveal whether a username exists. |
| Admin live updates | `conn_mgr.broadcast(..., scope="admin")` | The console can learn of a request at once. |
| `/v2` surface | `routers/v2`, `client_v2.json` | New routes are a deliberate, additive snapshot change (P-11). v1 is untouched. |

## 3. Proposed flow

1. The app sends username, device public key, a fresh nonce and a signature over them.
2. The server verifies the signature and stores a *pending* request with an expiry. It returns a
   request id and a short **match code**. An unknown username gets the same kind of answer.
3. The app shows the code, a countdown and **Cancel**, and polls.
4. The console shows worker, device, IP, age and code. The admin compares the code with the
   scanner, then approves or denies.
5. On approval the next **signed** poll gets a token pair, once. The request is then consumed.
6. The app continues as after a password login (device registration, `enterHome`).

States: `pending → approved → consumed`, or `pending → denied | cancelled | expired`;
`approved → expired` when not collected.

| Endpoint (draft) | Caller | Purpose |
|---|---|---|
| `POST /v2/auth/login-requests` | device, signed | create |
| `POST /v2/auth/login-requests/{id}/poll` | device, signed | status; tokens once when approved |
| `POST /v2/auth/login-requests/{id}/cancel` | device, signed | cancel |
| `GET /admin/login-requests` | admin | pending requests |
| `POST /admin/login-requests/{id}/approve`, `/deny` | admin | decide |

## 4. Rules to hold

- Tokens go only to the key that made the request; the id alone is worthless.
- Client-scope accounts only. A request must never produce an admin session.
- A revoked device cannot ask. A worker deleted or reset meanwhile invalidates the request.
- One pending request per device, limits per device and per IP, so nobody can flood the console.
- Approve is atomic: two admins, or approve racing cancel, produce at most one session.
- Who approved what, for which device, is logged. Tokens are never logged or kept in the row.
- The worker's other sessions are not touched, as with a password login.

## 5. Questions

| Ref | Question | Working default | Status |
|---|---|---|---|
| L1 | Which devices may ask? | Devices registered by an earlier login and not revoked. A new scanner needs one password login. | ✅ ⚠️ (delta R1) |
| L2 | Where are requests stored? | Redis with a TTL; audit in the log. A table only if you want request history. | ✅ ⚠️ (delta R1) |
| L3 | How long is a request valid? | 2 minutes, then 30 s to collect after approval. | ✅ ⚠️ (delta R1) |
| L4 | Match code | Yes, 2 digits, shown on both sides. | ✅ ⚠️ (delta R1) |
| L5 | Where does the admin approve? | Console: badge in the shell and a list on the Dashboard. Flutter admin: not built. | ✅ ⚠️ (delta R1) |
| L6 | Poll or push? | Poll every 2 s; `/v2/ws` needs a login ticket. | ✅ ⚠️ (delta R1) |
| L7 | Does a login lockout (429) block requests? | No: an admin decides, and it helps a locked-out worker. | ✅ ⚠️ (delta R1) |
| L8 | Redis down | Creating answers 503; password login still works. | ✅ ⚠️ (delta R1) |
| L9 | Alert when the console is closed? | No, open console only. | ✅ ⚠️ (delta R1) |

## 6. Task outline (planned: T6.21–T6.23, T7.12)

1. Backend: request store and service (state machine, expiry, limits, races).
2. Backend: `/v2` and `/admin` routes, WS message type, v2 snapshot and OpenAPI exports.
3. Console: badge, list, approve and deny.
4. Client: enable the button; waiting view with code, countdown, cancel and retry.
5. Docs: SYSTEM_REFERENCE §5, API, OPERATIONS; emulator end-to-end check.

Tests: signature and replay, unknown username, admin username, revoked device, double approve,
expiry on both sides, tokens handed out once, limits, worker deleted in between; contract v1
unchanged.
