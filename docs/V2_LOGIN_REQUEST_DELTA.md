# v2 login request: decisions

Decision delta for [V2_LOGIN_REQUEST_SPEC.md](V2_LOGIN_REQUEST_SPEC.md) (SPEC below). Where they
disagree, this file wins, and later rounds win over earlier ones. Code checked at `8bc4e5f`.

## Round 1 (2026-11-25)

### R1.1 Decisions

The working defaults of L1–L9 are **accepted for testing**: they are built as written and
reviewed after you have tried the feature.

| Ref | Decision | Status |
|---|---|---|
| L1 | Devices registered by an earlier login and not revoked. `pending` is enough until step 8. | ✅ ⚠️ after testing |
| L2 | Redis with a TTL, audit in the log, no table and no migration. | ✅ ⚠️ after testing |
| L3 | 2 minutes to decide, then 30 s to collect. | ✅ ⚠️ after testing |
| L4 | A 2-digit match code on both sides. | ✅ ⚠️ after testing |
| L5 | Vue console: badge in the shell and a list on the Dashboard. | ✅ ⚠️ after testing |
| L6 | The app polls every 2 s. | ✅ ⚠️ after testing |
| L7 | A password lockout (429) does not block requests. | ✅ ⚠️ after testing |
| L8 | Redis down: 503; password login still works. | ✅ ⚠️ after testing |
| L9 | No alert outside an open console. | ✅ ⚠️ after testing |

### R1.2 Consequences and corrections to the SPEC

- **No per-IP limit** (SPEC §4). The warehouse shares one network, the reason `login_throttle` is
  per username. Instead: one pending request per device (a new one replaces it), a limit per
  device, and a cap on all pending requests. L1 already shuts out unknown devices.
- **Unknown usernames and admin accounts** get a request that looks normal, never reaches the
  console and expires, so neither can be told apart from an ignored request.
- A signature covers a purpose prefix, the request id (or username, when creating) and a fresh
  nonce. A server-seen nonce is refused. On plain-HTTP LAN this does not stop someone who
  can read the traffic from reading the tokens, exactly as with password login today.
- `X-Client-Version` gates the device routes like the rest of `/v2`.

### R1.3 Open questions

None before planning. After testing: confirm or change L1–L9.
