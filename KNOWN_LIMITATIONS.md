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
  can. Pushing changes in real time and OTA updates remain open.
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
  - Shortfalls still never block a pick (HTTP 200, logged `pick_shortfall`). See OPERATIONS
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
  - Frontend admin configuration template: `frontend/admin/.env.example`
  - Agent instructions: `AGENTS.md`, `GEMINI.md`

---

### 7. Flutter Web Cross-Platform WebSocket Channel (admin web only)
- **Scope**: only the **admin** app runs in a browser. The operator client's web build was
  dropped (delta D2.1), so its `IOWebSocketChannel.connect` (`dart:io`) is correct for its
  Android and Windows targets. Earlier review item F-H7 no longer applies to it.
- **Rule for browser code**: `IOWebSocketChannel.connect` (from `package:web_socket_channel/io.dart`)
  crashes with `UnsupportedError` in a browser. Use `WebSocketChannel.connect(uri)` from
  `package:web_socket_channel/web_socket_channel.dart`, which picks `HtmlWebSocketChannel` on
  web and `IOWebSocketChannel` elsewhere.
- **Code References**: `frontend/admin/lib/app_state.dart` (uses `WebSocketChannel.connect`).

---

### 8. Operator Client API Is Frozen (Manual Client Updates)
- **Issue**: The operator client (`frontend/client`, Android/Windows scanners) is distributed and updated manually. It cannot be updated over the air, and its `BASE_URL`/`WS_URL` are baked into each build. Every backend version must keep working with every client build still in the field.
- **Policy**:
  - The client-facing API is **contract v1**. The exact surface is listed in `docs/BRANCH_SPLIT_REVIEW.md` §2.
  - Keep client API changes to a minimum. Only **additive** changes are allowed: new optional response fields, new endpoints, timezone offsets on datetimes, and new WebSocket event types whose `data` is a JSON **array of objects**.
  - **Breaking changes require a major version bump** and a manual client rollout. Examples: renaming or removing a path, field, or WS command; success codes other than `200`; making a field nullable; sending non-list WS `data` to client sockets; changing `acquire` 404 semantics. During the rollout the backend must serve the old and new contracts side by side, using path-versioned `/v2/...` routes for the changed operations only.
  - Supported targets: operator client on **Android and Windows** only (the client web build is dropped); admin on **web only** (the admin Windows build is dropped). The admin app ships with the backend, so the whole admin API may change as needed between releases. Backend internals may change freely too.
  - **Production is not strictly uptime-sensitive.** Short outages and maintenance windows are acceptable. After a backend restart longer than about 10 s, the client WebSocket stops retrying, and operators must tap *retry* on the connection banner. This is an operational note, not a deploy constraint.
  - Deploy constraints that still apply: keep the WS handshake rejection as HTTP 403. Do not change `JWT_ISSUER`/`JWT_AUDIENCE` (or `APP_ENV`, which sets their defaults) and do not replace `data/keys` outside a planned forced-relogin window (`docs/RELEASE.md`). Backend version bumps no longer change token identity (T3.1).
  - Decisions after the initial review are tracked in `docs/BRANCH_SPLIT_DELTA.md`.
- **Future Path**: The Sync Milestone (#3) adds version and settings discovery (`GET /meta`) and OTA prompts, so future client majors can negotiate. v1 clients will never call it.
- **Code References**:
  - Client API calls and WS parser: `frontend/client/lib/app_state.dart`, `frontend/client/lib/models.dart`
  - Contract inventory and plan: `docs/BRANCH_SPLIT_REVIEW.md`
  - Contract tests: `backend/tests/test_client_contract_v1.py` (HTTP snapshot `tests/contracts/client_v1.json`) and `backend/tests/test_ws_contract_v1.py` (WS frame rules, 403 handshake)

### 9. Dormant Password Minimum Length (Admin-Created Accounts)
- **Issue**: Passwords set through the admin app (`POST /admin/users`, `POST /admin/users/{username}/password`) accept any length from 1 character. A minimum length rule is written in the code but **commented out**.
- **Countermeasure**: The rule is a dormant hardening switch tagged `HARDENING(password-min-length)` in `backend/src/models.py` (`AdminUserCreate`, `AdminPasswordReset`), with a matching commented-out test in `backend/tests/test_admin_users.py`. Enable it by following `docs/OPERATIONS.md` → "Dormant Hardening Switches". Enabling it is a normal backend release with no client impact.
- **Scope**: It applies only to **new or reset** passwords. Existing passwords keep working at login, and the operator client's login/register requests (`UserAuth`, contract v1) are unaffected.
- **Code References**: `backend/src/models.py`, `backend/tests/test_admin_users.py`
