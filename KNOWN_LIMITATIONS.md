# Known Limitations

This document tracks known architectural, library, and system limitations within the codebase, along with recommended countermeasures and guidance for agents and developers.

---

## Agent Guidelines for Known Limitations

1. **Consult Prior to Debugging**: When debugging or completing tasks, review this document first to see if an issue or pattern has already been identified and has a recommended countermeasure.
2. **Mandatory Updates**: Whenever you encounter a new issue or implement a fix prompted by a user, you **must** update this file. Record the problem, the countermeasure, and a short reference to the fixed code. This maintains historical context and increases efficiency for subsequent agent invocations.
3. **Do Not Fix Blockers Unless Instructed**: If task completion is blocked by a known limitation, **DO NOT** attempt to fix the underlying limitation unless explicitly requested by the user. Instead, report the issue and provide a direct reference to the code affected by the limitation.

---

## Active Limitations & Countermeasures

### 1. SQLAlchemy ORM Session & Lazy Loading
- **Issue**: The project is not yet thoroughly tested for SQLAlchemy ORM usage. Operations may encounter runtime errors such as:
  ```text
  <object> is not bound to a session on attr read/update
  ```
  This typically occurs when attributes or relationships are lazily loaded on a detached instance outside an active session context.
- **Countermeasure**:
  - Update the query or ORM model implementation to use **eager loading** (e.g., `selectinload`, `joinedload`, or relationship configuration `lazy="selectin"`) rather than relying on default lazy loading.
  - Ensure operations accessing model relationships occur within the scope of an active database session.
- **Code References**:
  - *Add references here when fixes/patterns are implemented.*

---

### 2. API Stability & Production Hardening
- **Issue**: The admin API and backend internals still change between releases. Production hardening is tracked in `docs/IMPLEMENTATION_PLAN.md`. Startup rules per environment (`APP_ENV`), the production compose override, Redis auth, login throttling and request size limits are in place (step 2).
- **Countermeasure / Impact**:
  - The **operator client** API is frozen as contract v1 and protected by contract tests (see #8). Only the admin app and backend internals may change.
  - When making backend changes, keep `docs/API.md` updated with the latest endpoint specifications to prevent contract mismatches.
- **Code References**:
  - Backend API routers: `backend/`
  - API documentation: `docs/API.md`

---

### 3. Backend Settings & Version Metadata Synchronization to Frontends
- **Issue**: Backend settings, runtime configuration flags, and active bypass schemes (such as `MOCK_ORDER_BYPASS` and `STOCK_LOCATION_MODE`) are not synchronized to the frontend applications (Client and Admin). Furthermore, frontends have no built-in mechanism for discovering backend application update/version metadata or server configuration states.
- **Countermeasure / Impact**:
  - Frontends operate under default architectural assumptions and cannot dynamically reflect backend bypass modes (e.g. automatically adjusting single-location vs. multi-location stock UX or displaying active bypass banners).
  - Developers and operators testing the system must ensure frontend workflows align with the server's configured `.env` flags.
- **Partly resolved (v0.5, T4.7)**: the backend now publishes `GET /meta`: API version,
  supported client contract range, `app_env`, `stock_location_mode` and feature flags. The
  frozen v1 client does not read it. The admin app and the next client major (contract v2)
  can. Pushing changes in real time remains open.
- **OTA resolved for the v2 operator app (v0.6.0, T6.5)**: the backend serves
  `GET /v2/client/latest` and the APK; `min_supported_version_code` forces updates (426 /
  close 4426). The v1 Flutter client cannot update itself and is replaced by v2 by hand once.
- **Future High-Level Plan & Context**:
  - Resolving this synchronization gap is scheduled as a primary objective of the upcoming **Sync Milestone**.
  - In the Sync Milestone, the architecture will introduce:
    - **Over-The-Air (OTA) Updates**: Automated version check, compatibility negotiation, and OTA distribution of client/admin app updates.
    - **Dynamic Settings Synchronization**: Real-time broadcast and REST query capabilities for server-side settings, feature flags, and active bypass schemes, allowing frontends to dynamically adapt their UI and display active bypass states.
- **Code References**:
  - Backend configuration: `backend/src/config.py`, `backend/src/services/queries/stocks.py`, `backend/src/services/shopee_service.py`
  - Frontend state management: `frontend/client/lib/app_state.dart`, `frontend/admin/lib/app_state.dart`

---

### 4. Client Frontend Screen Real Estate & Card Layout Design
- **Issue**: Mobile and handheld scanner client devices operate under very limited screen real estate. When UI components implement fixed/frozen card headers above nested scrollable lists within constrained containers, the remaining scrollable area becomes too small to view useful item details or progress efficiently.
- **Countermeasure / Design Guideline**:
  - Avoid freezing card headers or nesting inner `ListView`s under fixed headers within constrained vertical layouts on the client frontend.
  - Build composite cards so that the entire card scrolls as a single unified scroll view (e.g. placing header padding, dividers, and item tiles together in a `ListView` or `SingleChildScrollView`). This allows the header to scroll out of view when operators need to inspect long item/BOM lists.
  - Maintain compact vertical padding and prioritize whole-card scrolling across all client scanner views.
- **Code References**:
  - Client orders view: `frontend/client/lib/screens/orders_view.dart`
  - Client scanner view: `frontend/client/lib/screens/scanner_view.dart`
  - Client stocks view: `frontend/client/lib/screens/stocks_view.dart`

---

### 5. Inventory Is Deduct-at-Pick, Not Reserved (resolved for restores in v0.5 / T4.3)
- **History**: picks once deducted stock without recording where it came from, so a deleted
  pick could not be restored and a concurrent pick could lose an update.
- **Now**:
  - One engine (`backend/src/services/queries/stocks.py`) with a `LocationPolicy` per
    `STOCK_LOCATION_MODE`.
  - Row locks, per-bin allocations (`orders.pick_stock_allocations`) and a structured
    `stocks_log`.
  - A delete restores exactly what was deducted.
  - Shortfalls still never block a pick (HTTP 200, logged `pick_shortfall`; see #14). See OPERATIONS
    "Inventory".
- **Remaining limits**:
  - Stock is *deducted* at pick time, not reserved until outbound close (stock Q6). Revisit
    only if the Integration milestone needs available versus on-hand stock.
  - There is no shortfall or reconciliation report yet (stock Q5: admin-only, later).
  - There is no per-item default bin. Deduction uses location order only.
  - A concurrent restore that recreates the same deleted bin can fail one request on the
    unique index. It is rare; retrying succeeds.
- **Code References**: `queries/stocks.py` (`apply_stock_update`, `deduct_for_pick`,
  `move_pick_quantity`, `restore_for_pick`), `queries/pick_items.py`,
  `tests/integration/test_stock_engine_pg.py`.

---

### 6. Environment File Inspection & Secret Isolation
- **Issue**: Active `.env` files in `backend/` and `frontend/admin/` contain live runtime secrets, database passwords, API signing keys, and production endpoints. Inspecting, grepping, or listing `.env` files via automated tools can trigger permission denial errors or risk leaking sensitive credentials into chat transcripts and logs.
- **Countermeasure**:
  - Automated agents, subagents, and tools **must never inspect, read, grep, or print active `.env` files**.
  - All automated agents must exclusively inspect `.env.example` templates (`backend/.env.example` and `frontend/admin/.env.example`) to discover available configuration keys, format specifications, and defaults.
  - Active `.env` files are strictly reserved for production use and manual local deployment.
- **Code References**:
  - Backend configuration template: `backend/.env.example`
  - Frontend configuration templates: `frontend/admin/.env.example`, `frontend/client/.env.example`
  - Agent instruction files (`CLAUDE.md`) point here; this file is the source of the rule.

---

### 7. Flutter Web Cross-Platform WebSocket Channel (admin web only)
- **Scope**: only the **admin** app runs in a browser. The operator client's web build was
  dropped (delta D2.1), so its `IOWebSocketChannel.connect` (`dart:io`) is correct for its
  Android target (the Windows build was dropped too, TH.3). Earlier review item F-H7 no longer applies to it.
- **Rule for browser code**: `IOWebSocketChannel.connect` (from `package:web_socket_channel/io.dart`)
  crashes with `UnsupportedError` in a browser. Use `WebSocketChannel.connect(uri)` from
  `package:web_socket_channel/web_socket_channel.dart`, which picks `HtmlWebSocketChannel` on
  web and `IOWebSocketChannel` elsewhere.
- **Code References**: `frontend/admin/lib/app_state.dart` (uses `WebSocketChannel.connect`).

---

### 8. Operator Client API Is Frozen (Manual Client Updates)
- **Issue**: The operator client (`frontend/client`, Android scanners) is distributed and updated manually. It cannot be updated over the air, and its `BASE_URL`/`WS_URL` are baked into each build. Every backend version must keep working with every client build still in the field.
- **Policy**:
  - The client-facing API is **contract v1**. The exact surface is listed in `docs/SYSTEM_REFERENCE.md` §10 (originally `docs/archive/BRANCH_SPLIT_REVIEW.md` §2).
  - Keep client API changes to a minimum. Only **additive** changes are allowed: new optional response fields, new endpoints, timezone offsets on datetimes, and new WebSocket event types whose `data` is a JSON **array of objects**.
  - **Breaking changes require a major version bump** and a manual client rollout. Examples: renaming or removing a path, field, or WS command; success codes other than `200`; making a field nullable; sending non-list WS `data` to client sockets; changing `acquire` 404 semantics. During the rollout the backend must serve the old and new contracts side by side, using path-versioned `/v2/...` routes that mirror the whole operator-client surface (V2-5 + `docs/V2_DELTA.md` D1, superseding A-5's "changed operations only"). Contract v2 is guarded by `tests/test_client_contract_v2.py` (snapshot `tests/contracts/client_v2.json`).
  - Supported targets: operator client on **Android** only (the client web and Windows builds are dropped); admin on **web only** (the admin Windows build is dropped). The admin app ships with the backend, so the whole admin API may change as needed between releases. Backend internals may change freely too.
  - **Production is not strictly uptime-sensitive.** Short outages and maintenance windows are acceptable. After a backend restart longer than about 10 s, the client WebSocket stops retrying, and operators must tap *retry* on the connection banner. This is an operational note, not a deploy constraint.
  - Deploy constraints that still apply: keep the WS handshake rejection as HTTP 403. Do not change `JWT_ISSUER`/`JWT_AUDIENCE` (or `APP_ENV`, which sets their defaults) and do not replace `data/keys` outside a planned forced-relogin window (`docs/RELEASE.md`). Backend version bumps no longer change token identity (T3.1). **Exception: v0.6.0** adds sessions and makes the `sid` claim required, so every device logs in once in that window (RELEASE.md "v0.6.0").
  - Decisions after the initial review are recorded in `docs/archive/BRANCH_SPLIT_DELTA.md` (archived 2026-11-21).
- **Future Path**: v0.6.0 serves contract v2 under `/v2` for the Kotlin operator app, which updates over the air (OPERATIONS "Publishing a client release") and negotiates via `/v2/meta` and `X-Client-Version`. v1 stays frozen until no v1 build remains in the field (V2_DELTA; removal is a later decision). v1 clients will never call `/meta`.
- **Versioning**: the backend (server) version and the API contract version are separate. The server version is SemVer per release (`pyproject.toml`, `server_version` in `/meta`); the contract version is an integer (`/v1`, `/v2`, `client_contract` in `/meta`) that changes only on a breaking operator-API change. The admin API is unversioned (it ships with the backend).
- **Cleanup when v1 is sunset** (versioning will be entirely cleaned up then): remove the deprecated `api_version` field from `/meta` and `/v2/meta` (a coordinated v2 snapshot change), the `config.API_VERSION` alias, and the `API_VERSION` environment name (rename the dev override to `SERVER_VERSION`).
- **Code References**:
  - Client API calls and WS parser: `frontend/client/lib/app_state.dart`, `frontend/client/lib/models.dart`
  - Contract inventory: `docs/SYSTEM_REFERENCE.md` §10; original review: `docs/archive/BRANCH_SPLIT_REVIEW.md`
  - Contract tests: `backend/tests/test_client_contract_v1.py` (HTTP snapshot `tests/contracts/client_v1.json`) and `backend/tests/test_ws_contract_v1.py` (WS frame rules, 403 handshake)

### 9. Dormant Password Minimum Length (Admin-Created Accounts)
- **Issue**: Passwords set through the admin app (`POST /admin/users`, `POST /admin/users/{username}/password`) accept any length from 1 character. A minimum length rule is written in the code but **commented out**.
- **Countermeasure**: The rule is a dormant hardening switch tagged `HARDENING(password-min-length)` in `backend/src/models.py` (`AdminUserCreate`, `AdminPasswordReset`), with a matching commented-out test in `backend/tests/test_admin_users.py`. Enable it by following `docs/OPERATIONS.md` → "Dormant Hardening Switches". Enabling it is a normal backend release with no client impact.
- **Scope**: It applies only to **new or reset** passwords. Existing passwords keep working at login, and the operator client's login/register requests (`UserAuth`, contract v1) are unaffected.
- **Code References**: `backend/src/models.py`, `backend/tests/test_admin_users.py`

### 10. Operator Client Release Builds Have No Network (v1 Runs as a Debug Build)
- **Issue**: A release build of the Flutter operator client cannot reach the server. The devices
  therefore run a **debug** build: JIT-compiled (slower), `debuggable` (app data readable over
  `adb run-as`), signed with a developer machine's debug key.
- **Cause**: A misconfiguration, not an Android limit. `android.permission.INTERNET` is
  declared only in `src/debug` and `src/profile/AndroidManifest.xml` (Flutter's template, for
  hot reload). `src/main/AndroidManifest.xml` lacks it, so release builds get no network. The
  cleartext rule for the LAN IP (`res/xml/network_security_config.xml`) is in `main` and works
  in both build types.
- **Countermeasure**: Declare `INTERNET` in `src/main/AndroidManifest.xml` before building a v1
  release APK (V2_DELTA Q23). The release build type is also signed with the debug key
  (`build.gradle.kts`), so it installs over a debug build only if built on the same machine;
  otherwise uninstall first (the operator logs in again). The v2 client declares `INTERNET` in
  its main manifest, and its OTA rehearsal uses the **signed release** APK.
- **Code References**: `frontend/client/android/app/src/main/AndroidManifest.xml`,
  `frontend/client/android/app/build.gradle.kts`

### 11. Console Sends a Wrong Shopee-Config Password Twice
- **Issue**: In the Vue console (Settings), one wrong admin password at "Unlock" reaches
  `POST /admin/shopee-config/unlock` **twice**, so the backend logs two failed unlock attempts
  (`Shopee config unlock failed: Incorrect password ...`) for one try. The user sees one
  "Incorrect password".
- **Cause**: The unlock endpoint answers a wrong password with **401**, the same status as an
  expired access token. The console's `HttpClient.send` treats every 401 as an expired session:
  it refreshes the tokens once and retries the request, which fails again with 401.
- **Impact**: Harmless today: no lockout counts unlock attempts, and the refresh succeeds.
  Keep it in mind when reading the logs, or before adding a lockout or rate limit to the unlock
  endpoint, since each wrong password would count double.
- **Countermeasure (not applied)**: either let the client skip the refresh-and-retry for this
  call (for example a per-request flag), or have the backend answer a wrong password with
  another status such as 403. The second is an admin API change: the Flutter admin
  (`config_view.dart`) would need checking too.
- **Code References**: `frontend/admin-web/src/api/http.ts` (`send`),
  `frontend/admin-web/src/stores/shopeeConfig.ts` (`unlock`),
  `backend/src/routers/admin_shopee.py` (`unlock_shopee_config`)

### 12. Orders That Can Never Show "Picked", and Orders That Stay Ongoing
- **Issue (a)**: An order with a BOM line that has no SKU (a custom item: `component_sku` is
  empty, shown as "No SKU") stays *Picking* in the console and the Android client: a pick always
  resolves to a catalog SKU, so that line can never be picked.
- **Issue (b)**: Since the ship-by cutoff was removed (V2_ORDERS_DELTA F4), an order stays
  ongoing until the sync sees it leave READY_TO_SHIP / PROCESSED / RETRY_SHIP, or a close
  completes it. An order whose detail Shopee stops returning, or a synthetic order from
  `scripts.seed_dev` under `MOCK_ORDER_BYPASS`, stays ongoing for good.
- **Impact**: Visible, not hidden: (a) the line is labelled "No SKU"; (b) the card is tagged
  *Late*. The admin can hand-tick either one.
- **Countermeasure (not applied)**: (a) let the BOM name a catalog SKU for custom items;
  (b) if stuck orders show up in practice, a console action to mark one done, or a long safety
  cutoff (for example 30 days past ship-by).
- **Code References**: `frontend/admin-web/src/lib/orders.ts` (`progress`),
  `frontend/client-android/.../ops/OrderLogic.kt` (`progress`),
  `backend/src/services/queries/orders.py` (`active_orders_query`, `local_active_order_sns`)

### 13. An Order Shipped on Shopee Locks Its Picks Without an Admin
- **Issue**: A Shopee sync closes an open outbound scan whose order is SHIPPED,
  TO_CONFIRM_RECEIVE or COMPLETED, and marks the order done (V2_ORDERS_DELTA C1). Operators can
  then no longer create or assign picks for it (409), even when it was packed but not fully picked.
- **Impact**: None where packed means done and ready to ship (the maintainer's operation, F11).
  In a strict operation, where every pick must be recorded before dispatch, the missing picks
  (and their stock deduction) can no longer be entered on the order.
- **Countermeasure (not applied)**: only auto-complete fully picked orders and leave the others
  for an admin to close, or allow picks on done orders.
- **Code References**: `backend/src/services/queries/outbound.py` (`close_shipped_outbound`),
  `backend/src/services/queries/pick_items.py` (`OrderClosedError`)

### 14. Picks Can Exceed Recorded Stock (Shortfall)
- **Issue**: By default a pick never fails for lack of stock. What is available is deducted; the rest is
  logged as `pick_shortfall` and has no allocation, so it is never restored. An order can
  therefore show more picked than was deducted, and a mistyped quantity can empty every bin of a SKU.
- **Impact**: By design: recorded counts can be behind the shelf, and picking should not stop.
  There is no shortfall report (#5); use the `stocks_log` rows with `reason = pick_shortfall`.
- **Countermeasure**: `STOCK_STRICT=1` rejects such picks (off by default, OPERATIONS "Strict
  stock"). v2 unassign removes the shortfall first, so undoing a mistyped quantity is exact.
- **Code References**: `backend/src/services/queries/stocks.py` (`deduct_for_pick`,
  `move_pick_quantity`, `restore_for_pick`)

### 15. Picks of a Cancelled Order Keep Their Stock Deducted
- **Issue**: An order cancelled on Shopee leaves the operator's list with its picks still on it.
  The stock stays deducted, and neither client shows those picks, so nobody can return them there.
- **Impact**: Recorded stock is too low once the goods are back on the shelf. An operator can
  correct the count in Stockkeeping. Deleting the pick afterwards would count it twice.
- **Countermeasure (not applied)**: a list of cancelled orders with picks, where the operator
  unassigns them (`docs/V2_PICKING_DELTA.md` Q65). Not automatic: only a person knows whether the
  goods are back.
- **Code References**: `backend/src/services/queries/orders.py` (`active_orders_query`),
  `backend/src/services/queries/pick_items.py` (`_active_order`)

### 16. The Bin of a Pick Is Assumed, Not Recorded (`multi` Mode)
- **Issue**: The operator never says which bin an item came from. The server deducts by location
  name, unlocated stock last, and stores that as the pick's allocation. Deleting a pick, and v2
  unassign, return stock to that **assumed** bin.
- **Impact**: If the item came from, or goes back to, another bin, the per-bin counts drift from
  the shelf. The SKU's total stays right. `single` mode is not affected.
- **Countermeasure**: transfer the stock in Stockkeeping. For future reference, not planned:
  (a) determine the bin when picking (scan or choose it), or (b) have the operator choose the bin
  when unassigning (`docs/V2_PICKING_DELTA.md` Round 2, Q68).
- **Code References**: `backend/src/services/queries/stocks.py` (`deduction_order`,
  `deduct_for_pick`, `restore_target`)
