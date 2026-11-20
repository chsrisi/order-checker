# Branch-split review: decision delta

This file records decisions made after [BRANCH_SPLIT_REVIEW.md](BRANCH_SPLIT_REVIEW.md)
(the "base review"). The base review is left untouched so it stays a snapshot of commit
`187122c`. Where the two disagree, **this file wins**, and later rounds win over earlier ones.
The stock pick/restore design has its own file:
[STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md).

**Nothing in these rounds has been implemented.** Code, README, OPERATIONS, and folder
removals are planned for later iterations.

Legend:

- ~~struck~~: answered or superseded
- **✅** decided
- **⚠️ revisit**: decided, but there is a follow-up for you
- **❓ open**: not answered yet; the stated recommendation is the working default
- **📌 kept**: kept for reference, no action

---

## Delta 1 (2026-11-20)

### D1.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| Platforms | **Drop the operator client web build and the admin Windows desktop build.** Supported targets become: operator client on **Android and Windows**, admin on **web only** (nginx-hosted, ships with the backend). | ✅ |
| Uptime | Production is **not strictly uptime-sensitive**. Short outages and maintenance windows are acceptable. Recorded in `KNOWN_LIMITATIONS.md` #8. | ✅ |
| §4 plan | Proposed plan (branch model, `APP_ENV` profile, contract protection, sequencing, runbook) **approved**. | ✅ |
| A-4 | **Return stock** when a pick entry is deleted. | ✅ (details: D2 and the stock discussion file) |
| A-6 | Answered by the platform decision: admin is web-only, so the admin API is not frozen. | ✅ |
| A-7 | As proposed: environment-specific `JWT_ISSUER`/`JWT_AUDIENCE` at the split, after F-C2 is fixed; one SemVer source; separate `CLIENT_CONTRACT=1`; `JWT_VERSION` decoupled from releases. | ✅ |

### D1.2 Effect on base-review findings

| Finding | Base review | After Delta 1 | Why |
|---|---|---|---|
| F-H7 client `IOWebSocketChannel` | High, needs client release | ~~High~~ → **closed (won't fix)** | The client no longer targets web, and `IOWebSocketChannel` is correct on Android and Windows. Known Limitation #7 now applies to the admin app only. |
| F-H8 client gives up reconnecting after ~10 s | High, keep deploy downtime < 10 s | ~~High~~ → **Low / operational** | Downtime is acceptable. Operators tap *retry* after a deploy. Fix it properly in the next client major (unlimited backoff). |
| F-M14 CORS | Medium, strip `*` and the localhost regex | **Simplified** | The admin web is same-origin through nginx, and the native client doesn't use CORS. Production can run with **no allowed origins at all**. |
| F-M18 secrets in query strings | `cfg_token` is admin-only, so it can move | Unchanged, but now clearly free to change | The admin API is unfrozen (A-6). |
| F-H6 row locks + F-M12 unit of work | Separate items | **Merged** with A-4 into "inventory transaction integrity" (step 4) | Stock restore is a stock mutation and needs the same locking. |
| L: nginx `pick_items` regex | Cosmetic | Unchanged (cosmetic) | Admin web is the only nginx consumer and never calls `/pick-items`. |
| L: Dockerfile runs migrations on every start | "racy for >1 replica" | **Acceptable** | Single replica plus tolerated downtime. Revisit only when scaling out. |

### D1.3 Effect on the plan

- **§2 frozen contract.** Unchanged in content. Its scope is now **only** the operator client
  (Android and Windows).
- **§4.1 branch model (A-1).** Accepted through plan approval: `master` = production, new `dev`
  becomes the default branch.
  - ⚠️ **revisit:** switching the *remote's* default branch to `dev` is a repository setting you
    need to change yourself (at step 3).
  - 📌 **kept:** the `client/vN` maintenance-branch idea stays in the plan for reference. Create
    one only when a client major ships.
- **§4.2 `APP_ENV` profile (A-2).** Accepted. CORS check per D1.2: with `APP_ENV=production`,
  refuse to start if *any* origin regex or `*` is configured, unless one is explicitly set.
- **§4.4 sequencing.** Superseded by the consolidated table in D2.3.
- **§4.5 runbook.** Relaxed:
  - ~~Keep backend downtime under 10 s~~. Downtime is acceptable; operators tap *retry* after a
    deploy.
  - **Still applies:** don't deploy *during key rotation* until F-C2 is fixed (mass logout).
  - **Still applies:** no `JWT_*` or key changes outside a planned relogin window.
  - **Still applies:** keep WebSocket handshake rejection as HTTP 403.
- **§4.6 what may change freely.** Widened to **the entire admin API**: `/admin/*`,
  `/auth/admin`, `/outbound/close`, `/shopee/reset-cache-state`, the WS `get_users` command,
  and admin-scope payloads. ~~The "coordinate with admin desktop" caveat~~ is removed.
  - 📌 **kept (standing rule):** events like `outbound_update` and `stocks_update` go to both
    admin and client sockets. Admin-only changes to them must be applied **per audience**, and
    the client-scope payload must keep matching contract v1. `ConnectionManager` already builds
    admin payloads separately; keep it that way.
- **§6 long-term.** Lower priority: distributed lock, Redis pub/sub fan-out, multi-worker.
  Keep the unit of work and moving sync off the request path.

### D1.4 A-4: stock restore on delete

- Restore belongs in the **same work item** as row locks (F-H6) and the unit of work (F-M12):
  "inventory transaction integrity", step 4. A restore shipped alone would race with picks and
  adjustments on the same SKU.
- `DELETE /pick-items/{id}` keeps returning 200 with the same body, so it is client-safe.
  Unassign is unchanged; it is not a stock movement.
- ~~⚠️ How much to restore~~ → being discussed in
  [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) (D2.2).
- ~~⚠️ Restore for assigned entries too?~~ → **both** (D2.1).

---

## Delta 2 (2026-11-20)

### D2.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| D1.3 §4.1 `client/vN` | Keep for reference. | 📌 kept |
| D1.3 §4.6 per-audience rule | Keep. | 📌 kept |
| D1.4.2 | Restore stock for **both** unassigned and order-assigned entries. **Document it in OPERATIONS**, because operations have never reached this edge case. | ✅. The note is drafted in the stock discussion file §7; add it to `docs/OPERATIONS.md` when the change is implemented. |
| D1.4.1 | Asked: how do (b) and (c) differ, is (c) the existing `StocksLog`, and what is recommended? | Answered in [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) §3–4. ⚠️ **revisit:** you need to choose an option. |
| A-3 | **Operator accounts are created by admins.** Public registration is disabled in production. | ✅ ⚠️ follow-ups (D2.2) |
| A-5 | Versioning model approved: **path-versioned `/v2/...` only for changed operations**; unprefixed paths stay v1; add `GET /meta`. | ✅ ⚠️ follow-ups (D2.2) |
| A-8 | Treat the single-location setting as a **mode**, not a bypass. Operations show a mode is the more accurate model. | ✅ ⚠️ follow-ups (D2.2) |
| A-9 | HTTP `GET /shopee/orders` returns **only the caller's own orders** for operators, the same as WS. | ✅ |
| A-10 | **Prioritize synthetic data** for dev. You will assess whether it is reliable enough. Rationale: Shopee OpenAPI Terms of Service and DPP (data protection policy). | ✅ ⚠️ follow-ups (D2.2) |
| Housekeeping | **Remove** `frontend/client/web/` and `frontend/admin/windows/`. | ✅. Done in a later iteration, together with the README, ARCHITECTURE, and Known Limitation #7 updates. |

### D2.2 Consequences and follow-ups

**A-3: admin-side account creation**

- **Ordering dependency.** Disabling `/auth/register` in production (step 2) leaves no way to
  create operators. Admin-side creation must therefore **ship in the same step**:
  - a new admin endpoint, e.g. `POST /admin/users` (admin API, free to add)
  - an admin web form
  - a `users_update` broadcast to admins
- The disabled `/auth/register` returns **403** with a `detail`. The v1 client keeps its
  Register button (frozen) and shows "Registration failed (Status 403)". Remove the button in
  the next client major. Dev keeps registration enabled (`ALLOW_REGISTRATION=1` default outside
  production).
- ~~❓ **open:** should admins also be able to **reset an operator's password**?~~ → ✅ yes (D3.1)
- ~~❓ **open:** may admins create **admin**-scope accounts?~~ → ✅ client scope only (D3.1)

**A-5: versioning**

- Unprefixed paths are permanent v1. Changed operations get `/v2/...` side by side. v1 is
  retired only when no v1 devices remain.
- `GET /meta` is additive. Proposed shape:
  `{api_version, client_contract: {min, max}, stock_location_mode, features: {...}}`.
  Planned for step 4, ahead of the Sync milestone, so the next client major can depend on it.
- ~~⚠️ **revisit:** should `/meta` be public or authenticated?~~ → ✅ public, non-sensitive fields only (D3.1)
- ~~⚠️ **revisit:** how will you know when v1 can be retired?~~ → **dropped** (D3.1). There is
  no `X-Client-Contract` header and no v1 traffic telemetry.

**A-8: stock location mode**

- Rename to `STOCK_LOCATION_MODE=single|multi`. Keep `SINGLE_LOCATION_STOCK_BYPASS` and the
  undocumented `STOCK_SINGLE_LOCATION_BYPASS` as **deprecated aliases** that log a warning.
- It is **allowed in production** and is **not** on the `APP_ENV=production` fail-fast list.
  Expose it via `/meta` (Known Limitation #3).
- Rewrite the OPERATIONS "Single-Location Stock Bypass" section as a "Stock location mode"
  section when implemented. Planned for step 2, alongside the `APP_ENV` work.
- ~~❓ **open:** default and production value~~ → ✅ default **`multi`** (D3.1)
- ~~⚠️ **revisit:** `multi` → `single` data merge~~ → ✅ one-off merge command at switch time (D3.1)

**A-9: operator order scope**

- The client-scope HTTP body becomes the caller's own orders. Admin scope is unchanged.
- Client-safe, because the client ignores the body and the 404 → refresh → re-acquire flow only
  needs a status 200 from the refresh. Planned for step 2 (privacy hardening).

**A-10: synthetic dev data**

- Dev never uses production Shopee partner credentials, shop ID, database dumps, or logs.
  Production logs contain usernames and order SNs. Dev uses the Shopee **sandbox** host only.
- `APP_ENV` guard: outside production, refuse to start if `SHOPEE_URL` is the live host
  (`partner.shopeemobile.com`), unless an explicit override is set. Planned for step 2.
- **Tracked seed tooling.** Today the only mock seed, `backend/temp/seed_mock_order.py`, is
  **git-ignored** (`backend/.gitignore` → `temp/`). Add tracked synthetic seeds, e.g.
  `backend/scripts/seed_dev/`, covering items, BOMs, stock, orders, and packages. Planned for
  step 3 (at the split).
- ⚠️ **revisit (your assessment):** how reliable is synthetic data compared with real Shopee
  payloads (status transitions, split packages, tracking timing)? Recommendation: build fixtures
  from **anonymized structure** (field shapes and status sequences) observed in the sandbox,
  never from production records.
- ~~❓ **open (DPP):** retention of recipient name and city~~ → ✅ **30 days** (DPP allows 90).
  Details and follow-ups in D3.2.

**Housekeeping (later iteration)**

- Delete `frontend/client/web/` (7 files) and `frontend/admin/windows/` (18 files).
- Update:
  - README lines 19–20
  - ARCHITECTURE "Frontends"
  - Known Limitation #7 (admin only)
  - TESTING Flutter commands, if they target removed platforms
- The admin app's `safe_storage_io.dart` conditional-import branch becomes unused. It can be
  simplified later but is harmless.

### D2.3 Consolidated sequencing (superseded by D3.3)

| Step | Branch | Content |
|---|---|---|
| 0 | `master` | Commit the review docs; write the client contract v1 tests and WS frame-shape test (base §4.3) |
| 1 | `master` | Client-safe correctness: F-C1, F-C2, F-H3, F-H4, F-H5, F-M1, F-M10, F-M11 |
| 2 | `master` | `APP_ENV` profile and fail-fast checks, `compose.prod.yaml`, Redis auth, prod CORS = none. **Registration flag plus admin user creation together** (A-3). HTTP order scoping (A-9). `STOCK_LOCATION_MODE` rename (A-8). Live-Shopee guard for non-prod (A-10). |
| 3 | create `dev`; tag `v0.4.0` | Maintenance window: A-7 forced relogin. Branch protection and CI split; remote default branch → `dev`. Tracked synthetic seed tooling (A-10). |
| 4 | `dev` | Performance (F-H1, F-H2, F-M13). **Inventory transaction integrity**: row locks, unique index, unit of work, stock restore per [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md), plus the OPERATIONS note. `GET /meta` (A-5). Datetime offsets (F-M6). Sync completeness (F-M2, F-M3). |
| 5 | `dev` | Admin API cleanup (`cfg_token` → header, pagination, dead code), admin password reset (if accepted) |
| any | any | Housekeeping folder removal and doc updates (next iteration) |

---

## Delta 3 (2026-11-20)

### D3.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| D1.4.1 | The stock model is **multi-location by default**, for a more robust and inclusive model. You asked whether both modes can be implemented based on the selected mode, and what that does to code redundancy. | ✅ default. Approach answered in [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) §8 (one engine plus a location policy). ⚠️ revisit: confirm the approach. |
| A-3a | Admins can **reset operator passwords**: `POST /admin/users/{username}/password`, which revokes that user's refresh tokens. | ✅ |
| A-3b | Admin-side creation is for **client-scope accounts only**. The seeded admin stays the only admin. | ✅ |
| A-5a | `GET /meta` is **public** and returns only non-sensitive fields (versions, `stock_location_mode`, feature flags). | ✅ |
| A-5b | **Dropped.** The API is not public (local use only), and you manage every operator device, so you know directly when v1 devices are gone. No `X-Client-Contract` header and no v1 traffic telemetry. | ✅ dropped |
| A-8a | `STOCK_LOCATION_MODE` defaults to **`multi`**. | ✅ |
| A-8b | Switching `multi` → `single` runs a **one-off merge command** at switch time. | ✅ |
| A-10b | Recipient data retention is **30 days**. The DPP allows up to 90; you have no use for the data beyond workers quickly matching order references. | ✅ ⚠️ follow-ups (D3.2) |

### D3.2 Consequences and follow-ups

**A-3a: password reset**

- In the same call, also **close that user's open WebSocket sessions**. This reuses the F-M9
  fix ("disconnect user's sockets"), so a reset cuts off every active session, not just future
  refreshes.
- It moves from step 5 to **step 2**, next to admin user creation. Once public registration is
  off, reset is the other half of account management.
- Minimum password policy: the current model only requires length ≥ 1. Recommendation:
  length ≥ 8 for admin-created and admin-reset passwords. The admin API is free to change.
  `/auth/login` still accepts existing short passwords, so this is client-safe.
  ~~❓ open: confirm the minimum.~~ → ✅ ≥ 8, shipped **commented out** (D4.2)

**A-5b: dropped CD consideration**

- Retiring v1 becomes a manual decision you make once every managed device is updated. The
  side-by-side `/v2` rule from A-5 still applies **during** that rollout, because devices are
  updated one by one.
- 📌 kept: because devices are managed and the API is local-only, the plan doesn't need
  public-API hardening beyond what is already listed (no API gateway or per-client keys). The
  F-C3 and F-C4 fixes still apply: anyone on the same network could otherwise register or reach
  Redis.

**A-10b: 30-day retention**

- **Mechanism.** A background task, like the refresh-token cleanup in `main.py` lifespan, with
  `RECIPIENT_RETENTION_DAYS=30` (setting it above 90 fails fast in production, per the DPP). It
  **deletes** the `shopee.order_recipient_address` row rather than blanking its fields, so no
  remnant is left. Client-safe: `recipient_address` is optional in both apps' parsers. Planned
  for **step 2** (privacy hardening).
- ~~⚠️ revisit~~ ✅ (D4.1) **Which clock starts the 30 days.** Orders that are never closed (cancelled,
  expired, never scanned) have no `done_at` and would keep personal data forever. Recommended:
  30 days after `done_at`, **or** after `ship_by` for orders that are not done.
- ~~⚠️ revisit~~ ✅ (D4.1) **Scope of personal data.** Recipient `name` and `city` are the obvious fields.
  Also consider:
  - `shopee.order_info.note`, the buyer's free-text note, which can contain names, phone
    numbers, or addresses. Recommendation: purge it on the same schedule.
  - Tracking numbers and order SNs. Recommendation: keep them. They are order references, not
    personal data on their own, and period close and history need them.
- ~~⚠️ revisit~~ ✅ (D4.1) **Backups.** Database backups (OPERATIONS "Backups & Persistence") keep purged
  rows for as long as the backup lives. Recommendation: keep backups no longer than 90 days so
  they stay within the DPP, and ideally 30 days to match. Document this in OPERATIONS when
  implemented.
- Logs: application logs don't contain recipient data today; they contain usernames, order SNs,
  and search queries. No action is needed, but keep it that way when adding logging. That rule
  goes into OPERATIONS with the retention section.

### D3.3 Consolidated sequencing (supersedes D2.3; amended by D4.4)

| Step | Branch | Content |
|---|---|---|
| 0 | `master` | Commit the review docs; write the client contract v1 tests and WS frame-shape test (base §4.3) |
| 1 | `master` | Client-safe correctness: F-C1, F-C2, F-H3, F-H4, F-H5, F-M1, F-M10, F-M11 |
| 2 | `master` | `APP_ENV` profile and fail-fast checks, `compose.prod.yaml`, Redis auth, prod CORS = none. **Registration flag, admin user creation, and admin password reset together** (A-3, A-3a), plus closing the user's sockets on delete or reset (F-M9). HTTP order scoping (A-9). `STOCK_LOCATION_MODE` rename, default `multi` (A-8). Live-Shopee guard for non-prod (A-10). **30-day recipient retention task** (A-10b). |
| 3 | create `dev`; tag `v0.4.0` | Maintenance window: A-7 forced relogin. Branch protection and CI split; remote default branch → `dev`. Tracked synthetic seed tooling (A-10). |
| 4 | `dev` | Performance (F-H1, F-H2, F-M13). **Inventory transaction integrity** using one engine with mode policies ([STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) §8): row locks, unique index, unit of work, stock restore, the `multi` → `single` merge command (A-8b), plus the OPERATIONS note. Public `GET /meta` (A-5a). Datetime offsets (F-M6). Sync completeness (F-M2, F-M3). |
| 5 | `dev` | Admin API cleanup (`cfg_token` → header, pagination, dead code) |
| any | any | Housekeeping folder removal and doc updates (next iteration) |

---

## Delta 4 (2026-11-20)

### D4.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| D1.4.1 | **One shared stock engine plus a `LocationPolicy` per mode** (`multi` default, `single` selectable), as in [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) §8. | ✅ |
| Stock Q1–Q6 | All recommendations accepted. The resulting rules are listed in D4.3. | ✅ |
| A-3a | Minimum password length ≥ 8 for admin-created and admin-reset passwords is **implemented as commented-out code**. Turning on the hardening later should only require removing the comment markers. | ✅ (D4.2) |
| A-10b | All follow-ups accepted. The clock is `done_at`, falling back to `ship_by` for orders never done. The buyer `note` is purged on the same schedule. Tracking numbers and order SNs are kept. Backups are kept ≤ 90 days, ideally 30. Recipient data must stay out of logs. | ✅ |
| A-10a, repo setting | Your own task and assessment; kept as is. | 📌 kept (yours) |

### D4.2 A-3a: how the dormant password rule is built (step 2)

The pattern mirrors the existing documented bypass blocks (`MOCK_ORDER_BYPASS`,
single-location), but goes the other way: the code is already written and is switched **on**
by removing comment markers.

- **Where:** only the new admin-side request models, e.g. `AdminUserCreate.password` and
  `AdminPasswordReset.password`. **Not** `UserAuth`. Login and the v1 client's register request
  keep `min_length=1`, so old short passwords still work at login. Client-safe.
- **Shape**, with one grep-able tag per spot:
  ```python
  password: str = Field(
      min_length=1,
      # HARDENING(password-min-length): to enforce, delete the line above and uncomment below.
      # min_length=8,
      max_length=256,
  )
  ```
  Add a matching commented-out test that asserts a 7-character password is rejected
  (`# HARDENING(password-min-length)`), so enabling the rule also enables its test.
- **Documented in two places** (when step 2 is implemented):
  - `docs/OPERATIONS.md`: a "Dormant hardening switches" section that lists each `HARDENING(...)`
    tag, what it does, and the enable steps (`grep -rn "HARDENING(" backend/`).
  - `KNOWN_LIMITATIONS.md`: a short entry stating that the rule is dormant and that existing
    passwords are unaffected when it is enabled (it applies only to new or reset passwords).
- **Decision for later (not now):** enabling it is a normal backend release, with no client
  impact.

### D4.3 Accepted stock rules (from Q1–Q6 and §8)

These are recorded here for implementation in step 4. The detail is in the stock discussion
file.

1. **Storage.** One engine. An allocation table (b2) is the restore source; a structured
   `StocksLog` (c-lite) is the audit trail. Both are written in the same transaction under row
   locks.
2. **Split (Q1).** Assigned parts take the **deducted** quantity first (FIFO by allocation id).
   Shortfall stays with the remainder.
3. **Restore target (Q2).**
   - `multi`: the original bin, recreating the row if needed.
   - `single`: the current sole location.
   - Both are logged.
4. **Deduction order (Q3).** The item's default location first, then other bins by `location`
   ascending.
5. **Legacy entries (Q4).** Never guess. Either restore nothing and log
   `pick_restore_skipped_legacy`, or clear open pick entries at the cutover maintenance window.
   ⚠️ **revisit (small):** pick one of the two at the step 3/4 maintenance window. The
   recommendation's two branches are equivalent in safety; clearing is simpler if operations
   can finish open picks first.
6. **Shortfall view (Q5).** An admin-only report, later.
7. **Deduct vs reserve (Q6).** Keep deducting at pick time.
8. **Mode policy (§8).**
   - Add a `LocationPolicy` with `resolve_target`, `before_write`, `deduction_order`, and
     `restore_target`.
   - Parametrize tests per mode.
   - Remove `get_or_merge_stock`.
   - Rename the log reason `bypass_merge` → `mode_merge`.

### D4.4 Sequencing amendments to D3.3

- **Step 2:** add the dormant `HARDENING(password-min-length)` rule, with its commented-out
  test and the OPERATIONS and KNOWN_LIMITATIONS notes.
- **Step 2 docs:** OPERATIONS gets the retention section (30 days, the `done_at` / `ship_by`
  clock, `note` purge, backups ≤ 90 days, no recipient data in logs).
- **Step 4:** carries rules D4.3 1–8 as written.
- **Step 3/4 maintenance window:** decide Q4's branch (D4.3 item 5).

---

## Delta 5 (2026-11-20)

| Ref | Decision | Status |
|---|---|---|
| Stock Q4 | **Clear open pick entries at cutover.** The cutover is the maintenance window in which the inventory-integrity release (step 4) is deployed to production. Operators finish their open picks first, then a maintenance command removes the remaining open entries **without** restoring stock. After the cutover, every entry has allocation data. | ✅ |
| Next | Write a full implementation plan and task guideline before any implementation starts: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Implementation starts only on your explicit go-ahead. | ✅ |

---

## Open questions and things to revisit

| Ref | Question | Working default | Status |
|---|---|---|---|
| ~~Stock Q4~~ | ~~Legacy pick entries at cutover~~ | Clear at cutover (D5) | ✅ |
| A-10a | Is synthetic data reliable enough? | Fixtures shaped from sandbox structure only | 📌 your assessment |
| D1.3 | Switch the remote default branch to `dev` | At step 3 | 📌 your task (repository setting) |

Resolved so far: ~~A-1~~, ~~A-2~~, ~~A-3~~ (admin creation), ~~A-3a~~ (reset), ~~A-3b~~
(client scope only), ~~A-4~~ (restore, both entry kinds), ~~A-5~~ (model), ~~A-5a~~ (public
`/meta`), ~~A-5b~~ (dropped), ~~A-6~~, ~~A-7~~, ~~A-8~~ (mode), ~~A-8a~~ (default `multi`),
~~A-8b~~ (merge command), ~~A-9~~ (own only), ~~A-10~~ (synthetic first), ~~A-10b~~ (30 days,
including all follow-ups), ~~D1.4.1~~ (`multi` default; engine plus policy), ~~Stock Q1–Q6~~
(recommendations; Q4 = clear at cutover), ~~A-3a minimum~~ (≥ 8, dormant),
~~housekeeping~~ (remove folders).
