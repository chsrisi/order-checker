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
- **Issue**: The project has not been thoroughly tested and hardened for production settings. As a result, backend APIs, request/response schemas, and endpoints may change frequently or unexpectedly.
- **Countermeasure / Impact**:
  - Frontend components and external consumers calling the API must account for API volatility.
  - When making backend changes, keep `docs/API.md` updated with the latest endpoint specifications to prevent contract mismatches.
- **Code References**:
  - Backend API routers: `backend/`
  - API documentation: `docs/API.md`

---

### 3. Backend Settings & Version Metadata Synchronization to Frontends
- **Issue**: Backend settings, runtime configuration flags, and active bypass schemes (such as `MOCK_ORDER_BYPASS` and `SINGLE_LOCATION_STOCK_BYPASS`) are not synchronized to the frontend applications (Client and Admin). Furthermore, frontends have no built-in mechanism for discovering backend application update/version metadata or server configuration states.
- **Countermeasure / Impact**:
  - Frontends operate under default architectural assumptions and cannot dynamically reflect backend bypass modes (e.g. automatically adjusting single-location vs. multi-location stock UX or displaying active bypass banners).
  - Developers and operators testing the system must ensure frontend workflows align with the server's configured `.env` flags.
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

### 5. Incomplete Inventory & Stock Keeping Logic during Item Picking
- **Issue**: The system's stock keeping logic has not been fully implemented end-to-end (historically only supporting inbound stocks via add/set stock operations). Discrepancies between physical inventory and tracked stock records could cause negative stock calculations during item picking.
- **Countermeasure / Milestone Context**:
  - Item picking (`POST /pick-items` / `create_pick_item_entry`) deducts the picked quantity from available warehouse inventory.
  - When a pick operation encounters insufficient stock (or no stock records exist for the item), the backend logs a warning, sets available stock to 0 (clearing depleted stock records), and completes the pick with a successful HTTP 200 response to avoid blocking warehouse operators.
  - Real-time updates for both `stocks_update` and `pick_item_entries_update` are broadcast via WebSockets.
  - This fix will be issued as part of the **Integration Milestone**.
- **Code References**:
  - Stock reduction query: `backend/src/services/queries/stocks.py` (`reduce_stock_for_pick`)
  - Pick item query: `backend/src/services/queries/pick_items.py` (`create_pick_item_entry`)
  - Pick item service: `backend/src/services/pick_item_service.py` (`create_pick_item_entry`)
  - Pick items router: `backend/src/routers/pick_items.py` (`create_pie`)

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

### 7. Flutter Web Cross-Platform WebSocket Channel
- **Issue**: Using `IOWebSocketChannel.connect` (from `package:web_socket_channel/io.dart`) directly in Flutter client/admin apps crashes with an `UnsupportedError` when running in a web browser, because `dart:io` WebSocket connections are not supported in browser runtimes.
- **Countermeasure**:
  - Always use `WebSocketChannel.connect(uri)` from `package:web_socket_channel/web_socket_channel.dart`.
  - The top-level `WebSocketChannel.connect` factory conditionally delegates to `HtmlWebSocketChannel` on web and `IOWebSocketChannel` on desktop and mobile.
- **Code References**:
  - Admin app state: `frontend/admin/lib/app_state.dart`
