# Order Checker v2 — frontend change, dual-contract backend, OTA

Status: **draft for discussion** (2026-11-21). Written by the maintainer with Claude (chat) from the
docs bundle only (README, docs/*, KNOWN_LIMITATIONS). **Nothing here has been checked against the
code.** Every claim about current behaviour must be verified before it drives a task; lines marked
**VERIFY** are the ones most likely to be wrong.

**Decisions after this draft are logged in [V2_DELTA.md](V2_DELTA.md). Where they disagree,
the delta wins** (later rounds over earlier ones), as BRANCH_SPLIT_DELTA did for its review.
§10 (code verification) and §11 (feasibility) were added by Claude Code on 2026-11-22.

Audience: Claude Code, working in this repo. Continue the discussion with the maintainer here, check
the spec against the codebase, then turn it into tasks in `docs/IMPLEMENTATION_PLAN.md` (new step,
same format and guardrails as steps 0–5). Do not start implementing until the maintainer approves.

---

## 1. Goals

1. Replace the Flutter frontends with lighter stacks:
   - **Operator client v2:** native Android (Kotlin + Jetpack Compose), Android 11 target.
   - **Admin:** Vue (+ Vite), static build, web only.
2. Give the operator client **OTA updates**, so devices never need to be collected again after the
   v2 install day.
3. Serve **client contract v1 and v2 from one backend process** while the fleet migrates.
4. Keep warehouse operations running every day of the migration. v1 stays fully usable until v2 is
   proven.

Non-goals: changing contract v1; a second backend deployment; running more than one backend
process (Uvicorn `--workers`, see §10.1); Windows or web builds of the operator client.

Operations today: **two operator devices work at the same time** (maintainer, 2026-11-22). The one
backend process already serves them concurrently; that is not "multi-worker" in the sense above.

---

## 2. Decisions taken (2026-11-21, maintainer)

| ID | Decision |
|---|---|
| V2-1 | Operator client v2 is **Kotlin + Jetpack Compose**, native Android only, targeting Android 11 (API 30). Not a browser or WebView app. |
| V2-2 | **Windows is dropped for the client in v0.5.0.** It was used only for UI development. Platforms may be revisited later if the new stack makes development easier. |
| V2-3 | New admin is **Vue + Vite**, web only, served as static files at **`/admin/`**. |
| V2-4 | **One backend** serves both contracts. No second backend instance (it would split WS fan-out, the sync lock and the Shopee cache, which are process-local). |
| V2-5 | v2 API is mounted at **`/v2/`** and **mirrors the full surface** with unchanged paths (`/v2/auth/login`, `/v2/pick-items`, …), not only the changed operations. **This supersedes A-5** ("`/v2` only where operations change"); record it in the plan as a new decision. |
| V2-6 | The Flutter admin keeps running at its current path until the Vue admin reaches parity; screens are ported one by one, then the Flutter admin is retired. |
| V2-7 | On the device day, **OTA + install of v2 alongside v1 is the priority**, ahead of feature completeness. |
| V2-8 | Learning a new language is not a constraint on stack choice. |

Rejected alternatives (for the record): React Native (JS runtime, not lighter than Flutter),
Capacitor/Ionic (WebView), HTMX + Jinja admin (needs cookie auth + CSRF and HTML-fragment WS; ties
admin to backend releases), React admin (fine, but Vue has more batteries for an admin of tables
and forms; revisit only if a shared TypeScript client becomes valuable).

---

## 3. Backend: dual contract in one process

### 3.1 Routing

- Root routes = **contract v1, frozen**. No change, still guarded by
  `tests/test_client_contract_v1.py`, `tests/test_ws_contract_v1.py` and
  `tests/contracts/client_v1.json`.
- `APIRouter(prefix="/v2")` mounts the v2 surface. Where a v2 operation is identical to v1, reuse the
  same handler/service; where it differs, write a v2 handler over the **same services and queries**
  (routers stay thin, per ARCHITECTURE "Backend layers").
- Add a v2 contract snapshot (`tests/contracts/client_v2.json`). It is not frozen, but changes must
  be deliberate and coordinated with an app release.
- **VERIFY:** how routers are included in `src/main.py`, whether any route depends on its path (e.g.
  hard-coded redirects, `url_for`), and how the OpenAPI snapshot test will treat duplicated routes
  (consider separate tags or a separate schema for v2).
- **Admin routes:** decide whether `/admin/*` API endpoints stay at the root (admin is not a
  "client contract") or move. Note the clash: the Vue admin's **static files** are served at
  `/admin/` too. **VERIFY** existing admin API paths (`/admin/users`, `/admin/history/*`,
  `/admin/export/*`, …) against the static path and pick a non-colliding layout (e.g. static at
  `/admin/` with API calls kept on their current paths, and nginx routing `/admin/` only for
  non-API paths — or move the static app to a distinct prefix). Raise with the maintainer.

### 3.2 WebSocket

- One `ConnectionManager` holds v1 and v2 sockets. Each connection is tagged with its contract
  version at handshake (v2 handshake path under `/v2/`).
- Broadcast builds the payload **once per (audience, contract version)**, keeping the T4.5 rule of
  building payloads once.
- v1 frames unchanged: `data` is a list of objects; handshake rejection stays HTTP 403.
- v2 frame format is free to design (proposal: typed envelope `{type, data, ts}` parsed by `type`
  first, which was already on the client v2 backlog).
- Result: events from v1 devices reach v2 devices and both admins, and vice versa.

### 3.3 Shared state and data rules

- Same database, users, tokens, JWKS, iss/aud, Redis tickets, sync cache and lock. No token identity
  change, so **no forced relogin** for this work.
- Any new state v2 introduces (new order states, new fields with meaning) must still be shown
  sensibly to v1 clients while both are in use. Additive migrations only during the overlap.

### 3.4 Versioning, `/meta` and OTA endpoints

- `/meta`: `client_contract` becomes `{min: 1, max: 2}`.
- New `GET /v2/client/latest` (auth required? **decide**; the APK is internal):
  `{version_code, version_name, apk_url, sha256, min_supported_version_code, notes}`.
- APK files are served as static files by nginx (path to decide, e.g. `/downloads/client/`).
  Publishing a release = upload APK + update the metadata (source: file, config or DB table —
  **decide**; a file next to the APK is simplest).
- The v2 client sends `X-Client-Version: <version_code>` on every request and the WS handshake.
  If below `min_supported_version_code`, the backend answers **426 Upgrade Required** (WS: reject
  with a defined close code) so the app forces the update screen.

### 3.5 Retiring v1

- When every device runs v2: a major backend release removes the root client routes and v1 WS
  framing, sets `client_contract.min = 2`, and deletes the v1 contract tests. Until then, nothing in
  v1 changes.

---

## 4. Operator client v2 (Kotlin + Compose)

### 4.1 Platform and build

- `minSdk`/`targetSdk`: Android 11 (API 30) as target; confirm `minSdk` against the actual devices.
- **applicationId differs from the Flutter client**, so v1 and v2 install side by side. Do not reuse
  the v1 package name.
- Release signing key: generated once, **backed up outside the repo** (maintainer). A lost key means
  no OTA update can ever install over the app.
- New directory, e.g. `frontend/client-android/` (**decide**). Flutter `frontend/client/` stays until
  v1 is retired.
- CI: Gradle build + unit tests + lint added to `.github/workflows/ci.yml`; release APK artifact.

### 4.2 Screen and input design

- Devices are handheld scanners with a **physical keyboard**: design for no soft keyboard, use the
  full screen, large touch targets, compact vertical padding.
- Keep KNOWN_LIMITATIONS #4: whole-card scrolling, no frozen headers over nested lists.
- Scanner input: **open question** — keyboard wedge vs intent broadcast (e.g. Zebra DataWedge,
  Honeywell, Urovo). Prefer intents where available; keep a keyboard-wedge fallback. Barcode
  resolution stays server-side (`resolve_barcode_to_item`).

### 4.3 Feature scope (parity with v1)

From ARCHITECTURE "Frontends": login/logout, order list and claiming (`acquire`), pick list and
pick entries, outbound label scanning, item lookup, stock adjustment and transfer, live updates over
WS, reconnection. **VERIFY** the full v1 surface in `SYSTEM_REFERENCE.md` §10 and map each item.

Backlog items to fold in (IMPLEMENTATION_PLAN §5 "Client v2"): unlimited reconnect backoff (F-H8),
URL-encoded queries, parse WS frames by `type`, no Register button, use `/meta` (location-mode UX),
typed API client generated from OpenAPI, state split per feature (no single `AppState`), compare
resolved SKUs in the over-quantity warning, clear orders and picks on logout.

### 4.4 OTA updater

- On start, on resume and periodically: call `/v2/client/latest`.
- If newer: download APK, verify SHA-256, install via `PackageInstaller` session. Needs
  `REQUEST_INSTALL_PACKAGES` and the per-app "install unknown apps" permission (granted once per
  device on install day).
- Without device-owner/MDM, each install needs one operator tap. Forced updates use the 426 path.
- **Open question:** is device-owner mode or an MDM available? It would allow silent installs.

### 4.5 Configuration

- Base URL: v1 baked it into each build. For v2, prefer build-time default + a hidden admin/settings
  screen (or QR provisioning) so a server move doesn't need a rebuild. **Decide.**
- Tokens in Android Keystore-backed storage (EncryptedSharedPreferences or DataStore + Keystore).
- JWKS verification as in v1 (refresh JWKS after a failed verification).

---

## 4A. Device model and admin control of clients (v2 only)

Goal: the admin can see and control individual operator devices: remote logout, assign an
operator to a device (no password typed on the device), force an update, push config. This is
**not** done through `/meta`, which stays public, global, read-only and non-sensitive (T4.7).

### 4A.1 Device registry

- New table (proposal `auth.devices`): `id`, `label`, `model`, `android_version`,
  `app_version_code`, `public_key`, `status` (`pending` | `active` | `revoked`), `current_user`,
  `enrolled_at`, `last_seen_at`.
- Each v2 install generates a **keypair in the Android Keystore**; the public key is the device
  identity. Device requests are authenticated with a device credential (signed challenge or a
  device token issued at enrollment — **decide**).

### 4A.2 Enrollment

Two paths, both supported:

1. **QR enrollment** (device day): admin generates a short-lived enrollment code/QR, the device
   scans it and registers as `active`.
2. **Bootstrap enrollment** (works later over OTA): the first operator login on a v2 device
   registers it as `pending`; an admin approves it in the admin app.

**Device-day requirement:** the first v2 build must already generate the keypair and perform the
`pending` registration, even if the admin screens come later, so every device is identifiable.

### 4A.3 Device-scoped sessions and instant revocation

- `refresh_tokens` gains a nullable `device_id` (additive migration). **VERIFY** the existing table;
  `revoked_at/ip_address/agent` exist but are never written (SYSTEM_REFERENCE §14.6).
- Tokens carry a session id claim `sid`. Revocation is checked per request against active sessions
  (Redis), so a remote logout takes effect immediately instead of after the 15-minute access TTL.
- Revoking a device kills all its sessions and its device credential (lost or stolen scanner).

### 4A.4 Command channel

- A v2 device keeps a **device-level WS connection** (authenticated as the device, independent of
  user login), so it can receive commands while logged out.
- Commands: `logout`, `assign_user` (backend issues that operator's tokens to the device),
  `update_now`, `refresh_config`. The device acknowledges each command.
- Commands are also persisted as the device's **desired state**; an offline device pulls it from
  `GET /v2/device/state` on reconnect.
- Audit: every action records both the user and the device. `assign_user` means whoever holds the
  scanner acts as that operator — acceptable for shared warehouse devices, but must be logged.

### 4A.5 Protected per-device config

- `GET /v2/device/config` (device-authenticated) carries device-specific settings. This is the
  "protected meta"; it also covers the settings-sync part of KNOWN_LIMITATIONS #3 (Sync Milestone).

### 4A.6 Backward compatibility with v1 login

- Root `/auth/login` and `/auth/refresh` keep their exact request/response shape and create ordinary user
  sessions with `device_id = NULL`. v1 sockets never receive device commands.
- Adding `sid` to all tokens is additive. **VERIFY** the v1 client does not parse claims strictly
  (it verifies signatures via JWKS with `jose`).
- Applying the instant-revocation check to **v1** tokens is optional (admin could kill a v1 user's
  sessions, not per device) but is a behaviour change: a revoked v1 session gets 401 before expiry.
  **VERIFY** how the v1 client handles 401 before enabling it for v1. Default: v2 only.
- Contract v1 tests must stay green; any `client_v1.json` change must be additive.
- v2 also keeps normal username/password login (session bound to the device); `assign_user` is an
  extra, not the only way in.
- Security note: if v2 later requires enrollment before login, the v1 login remains an unenrolled
  way in until v1 is retired — another reason to set a v1 retirement date (§8 Q8).

### 4A.7 Admin screens

Device list (status, user, app version, last seen), approve/revoke, generate enrollment QR,
logout, assign operator, force update, edit device config.

---

## 5. Admin (Vue + Vite) at `/admin/`

- Static build (`base: '/admin/'`), nginx SPA fallback, same origin as the API (no CORS).
- Uses the existing JSON admin API and WS unchanged. Bearer tokens as today; decide storage
  (memory + refresh token in storage, mind XSS).
- Suggested libraries (decide): Vue Router, Pinia, a table/form UI kit (Naive UI or Element Plus),
  generated TypeScript types from `/openapi.json`.
- Port order (proposal): login → users → orders/scan history (paginated, `X-Total-Count`) →
  inventory → period closure → BOM inspection → Shopee token config (`X-Config-Token`) → CSV exports.
- **During the overlap the admin API is no longer "free":** both admins call it. Changes are
  additive; remove or alter an endpoint only after its screen has moved to Vue.
- Browser download of CSV exports: already fixed in the Flutter admin for v0.5.0 (TF.1, ex
  KNOWN_LIMITATIONS #10). The Vue admin does the same (Blob URL + `<a download>`).
- Directory: e.g. `frontend/admin-web/` (**decide**).

---

## 6. Device day plan (one day with the devices)

Priority order. Anything not finished is shipped later over OTA.

1. Build and sign a v2 release APK with a **working updater**, login, and device keypair +
   `pending` registration (§4A.2).
2. On every device: install v2 next to v1, grant "install unknown apps" for v2, log in once, test one
   OTA update end to end (publish a dummy newer build and update to it).
3. Record device models, Android versions and scanner type per device.
4. Only then: as much feature parity as time allows. Operators keep using v1 for anything v2 can't
   do yet.

---

## 7. Release placement

- v0.5.0 already carries the inventory migration and cutover (RELEASE.md §5). **Decide** whether the
  `/v2` backend surface ships in v0.5.0 or a following release; the device day needs at least the
  OTA endpoints and enough `/v2` routes for login.
- nginx: proxy `/v2/` to the API; serve `/admin/` (Vue static, SPA fallback); serve the APK path;
  keep the existing admin path and current proxy list. **VERIFY** `frontend/admin/nginx.conf.template`
  (T5.4 already added `/meta`).
- Docs to update when implemented: ARCHITECTURE, API, SYSTEM_REFERENCE §10 (+ new v2 section),
  KNOWN_LIMITATIONS #3, #7, #8, OPERATIONS (OTA publishing), RELEASE (APK release steps), TESTING.

---

## 8. Open questions

Current status of each question, and the questions added since: [V2_DELTA.md](V2_DELTA.md)
"Open questions".

1. Scanner devices: brand/model, Android version, scan delivery (intent vs keyboard wedge)?
2. ~~Number of devices~~ (answered: two, used at the same time); is device-owner/MDM possible?
3. v2 backend in v0.5.0 or a later release?
4. Admin API path vs `/admin/` static path layout (§3.1).
5. `/v2/client/latest`: authenticated or public? Metadata source?
6. Client base URL configuration (§4.5).
7. Directory names for the two new frontends.
8. Criteria and date for retiring v1 and the Flutter admin.
9. Device credential: signed challenge per connection or a device token issued at enrollment (§4A.1)?
10. Apply instant revocation (`sid` check) to v1 tokens, or v2 only (§4A.6)?

## 9. Related known issues (separate, forwarded by the maintainer)

Ex KNOWN_LIMITATIONS #10 (admin CSV export on web), #11 (`GET /stocks` 500 without
`join_warehouse=true`), #12 (deleting a user does not restore picked stock): **all three are already
fixed in v0.5.0** (IMPLEMENTATION_PLAN tracker TF.1–TF.3) and removed from KNOWN_LIMITATIONS, which
now ends at #9. v2 routes reuse the fixed services, so they inherit the fixes.

---

## 10. Verification against the code (Claude Code, 2026-11-22)

Checked on `dev` at `c1e03dc`. Where this section and the text above disagree, this section wins.

### 10.1 Process model and the two devices

- The backend runs **one Uvicorn process** (`backend/Dockerfile:55`, no `--workers`). WebSockets,
  sync cache and lock, and the Shopee circuit live in that process (SYSTEM_REFERENCE §3, §14.1).
- "Multi-worker" in docs and the backlog means several backend processes. It does not mean
  several operators. One async process handles both devices at once, as it does today.
- Two devices make a **pilot** cheap: move one device to v2 while the other stays on v1, then
  move the second. The dual-contract backend (§3) supports this.
- With two devices, §4A is a lot of machinery (registry, enrollment, command channel). Consider
  doing it in stages. The device-day minimum (keypair + `pending` registration, §4A.2) still
  applies.

### 10.2 Routing (§3.1)

- `src/main.py:223-232` includes 12 routers at the root. Each router has its own prefix (`/auth`,
  `/admin`, `/outbound`, `/items`, `/stocks`, `/shopee`, `/pick-items`, `/ws`; jwks and `/meta`
  have none). `app.include_router(r, prefix="/v2")` can mount a router a second time.
- No route depends on its own path: no `url_for`, no redirects. `request.url.path` is used only
  for logging (`main.py:127`, `exceptions.py:23`).
- OpenAPI: `test_client_contract_v1.py` looks up the exact v1 paths, so `/v2/...` copies do not
  disturb it. FastAPI's default operation IDs include the path, so they stay unique.
  `test_openapi.py` requires a summary and description on every operation, and reused handlers
  already have both. Tag v2 routes separately (e.g. `v2 · pick items`).
- **Risk:** v1 and v2 share Pydantic models, so changing a shared model for v2 changes v1. The
  v1 snapshot test catches this, and the fix is a separate v2 model with a distinct class name.
  Two models with the same class name in different modules give confusing OpenAPI component
  names.
- **Scope of V2-5:** does "full surface" include the admin API (`/v2/admin/*`)? Proposal: `/v2`
  covers what the operator client calls, plus the new device/OTA endpoints. The admin API stays
  at the root, because it ships with the backend and is not a client contract. **Decided** (delta
  D1).

### 10.3 `/admin/` path collision (§3.1, §5, V2-3)

- The admin nginx (`frontend/admin/nginx.conf.template`) sends
  `^/(auth|admin|outbound|items|stocks|shopee|pick-items|meta|\.well-known)(/|$)` to the backend
  and serves the Flutter admin at `/` with an SPA fallback.
- So **`/admin/` already belongs to the API.** A Vue app there would need every admin API call
  moved, and that breaks the Flutter admin during the overlap (V2-6).
- Proposal: serve Vue at a prefix the regex does not match, e.g. **`/console/`** (`base:
  '/console/'`). When the Flutter admin retires, Vue can take over `/`. V2-3 changes accordingly.
  **Decided: `/console/`** (delta D1).

### 10.4 Who goes through nginx (§3.4, §7)

- The operator client calls Uvicorn directly. `frontend/client/.env.example` has
  `BASE_URL=http://${BASE}:8000`, and `compose.prod.yaml` keeps the `server` port mapping (it
  resets only `db` and `redis`). Check the real production client `.env` by hand; agents may not
  read it (KNOWN_LIMITATIONS #6).
- Consequences:
  - A `/v2/` nginx proxy is needed only if the Vue admin calls `/v2`.
  - The APK must be reachable from the devices. Either FastAPI serves it from a mounted volume
    (same `:8000` the devices already use), or the admin-web nginx serves it (a second host and
    port for the device). The first option is simpler for the updater. **Decided: the backend
    serves it** (delta D1).
  - `X-Client-Version` and the 426 response never pass through nginx for the client.

### 10.5 WebSocket (§3.2)

- `ConnectionManager` (`services/managers/connection_manager.py`) maps username → sockets and
  stores a scope per socket. `broadcast` builds one payload per audience (`*`, `admin`,
  `user:<name>`), and `_send_raw` wraps it as `{"type", "data"}` for each socket.
- Tagging each socket with its contract version and wrapping by version in `_send_raw` is a small
  change. The payload stays built once per audience, and only the envelope differs. T4.5 holds.
- The handshake rejects with `WebSocketException` 403 before accept (`routers/websocket.py`). A
  v2 path can use a defined close code instead. Contract v1 needs 403 only on `/ws`.

### 10.6 Tokens, sessions and revocation (§4A.3, §4A.6)

- `auth.refresh_tokens` is as described: `jti`, `username`, `created_at`, `expires_at`,
  `revoked_at`, `ip_address`, `agent`, and the last three are never written. Revocation deletes
  rows. Adding `device_id` is additive.
- **`sid` versus rotation:** every refresh deletes the row and issues a new `jti`, so nothing
  stable identifies a session today. `sid` needs storage that survives rotation: a `session_id`
  column on `refresh_tokens`, or a sessions table.
- **Backend claim check:** `auth_service.py:46,70` decodes with
  `require: [exp, nbf, sub, aud, iss, jti, iat]`. `sid` must stay optional during verification
  until every pre-`sid` token has expired (refresh TTL 24 h). Making it required at once forces
  a relogin.
- **v1 client claims:** `frontend/client/lib/app_state.dart:77-105` verifies the signature
  against JWKS and then reads only `exp` (as int). An extra `sid` claim is safe.
- **v1 client on 401:** any 401 triggers one refresh and one retry. If the refresh fails, the
  client logs out to the login screen (SYSTEM_REFERENCE §10, §12). So the instant-revocation
  check on v1 tokens leads to a clean logout, provided the session's refresh rows are deleted
  too. Otherwise the refresh succeeds and the revocation does nothing.
- **Sockets:** a socket is authenticated once, at the handshake. Revoking a session must also
  close its sockets, as a password reset already does (`disconnect_user`, code 1008).

### 10.7 Versioning and client facts

- `/meta` already returns `client_contract {min, max}` from `config.CLIENT_CONTRACT_MIN/MAX`
  (`config.py:187-189`, all `1`). §3.4 needs a config change plus `test_meta.py`, nothing more.
- Send 426 only on `/v2` and only when `X-Client-Version` is present and too old. v1 treats any
  non-200 as an error.
- v1 `applicationId` is `com.example.frontend` (`frontend/client/android/app/build.gradle.kts:24`),
  with `minSdk`/`targetSdk` left at Flutter defaults. v2 needs a real, distinct ID (e.g.
  `com.bakingholic.orderchecker`), chosen once, because it can never change for OTA.
- V2-2 (Windows dropped) is a **new** decision. `frontend/client/windows/` still exists, and
  KNOWN_LIMITATIONS #8 and SYSTEM_REFERENCE §1/§12.1 still list Android + Windows. It needs a
  task: delete the folder and update the docs. CI has no Windows job.
- V2-5 supersedes A-5, which the docs repeat in two places: IMPLEMENTATION_PLAN §5 ("`/v2` routes
  only where operations change") and KNOWN_LIMITATIONS #8 ("for the changed operations only").
  Update both when the plan step is written.

---

## 11. Feasibility (Claude Code, 2026-11-22)

Verdict: **feasible with the current team, stack and infrastructure. There are no blockers in
the code.** The real risk is the one day with the devices: whatever the first v2 build gets
wrong in the updater cannot be fixed over the air. §11.3 is about that risk.

### 11.1 Per workstream

| # | Workstream | Feasible? | Size | Main risk / note |
|---|---|---|---|---|
| W1 | Backend `/v2` client surface + v2 WS framing (§3, §10.2, §10.5) | yes | S–M | The client routers mix in admin operations (`/outbound/close`, `/shopee/reset-cache-state`, `/auth/admin` live in the same routers as client calls). So a second `include_router` would also mirror admin operations. Build a `routers/v2/` module that registers the client operations one by one (`add_api_route` with the existing endpoint functions where unchanged). `client_v2.json` snapshot via the existing `build_contract`, with the operation list as a parameter. |
| W2 | OTA endpoints + release publishing (§3.4) | yes | S | The backend serves the APK (D1) from a mounted volume beside `data/keys` (e.g. `data/releases/client/`), using `FileResponse`, so no new dependency. Publishing a release is a script (`scripts.publish_client_release <apk>`) that computes the SHA-256 and writes `latest.json`. |
| W3 | Android client core: project, signing, login, updater, device keypair + `pending` registration | yes | M | This is the device-day critical path (§11.3). Local toolchain present: Android SDK (platform 37, build-tools 37, emulator), JBR 25, system JDK 27. Gradle comes in through the wrapper. |
| W4 | Android feature parity | yes | M–L | v1 client is ≈3.5k lines of Dart. `orders_view.dart` (1.1k) and `app_state.dart` (0.9k) carry most of the logic. Scanning in v1 is **keyboard wedge**: a focused `TextField` plus `onSubmitted` (Enter suffix). A Compose text field with an IME action does the same, so wedge needs nothing device-specific. Intents are optional. |
| W5 | Device registry, enrollment, sessions, command channel (§4A) | yes | L | The largest piece, and the least needed with two devices (§10.1). Stage it: (a) device day: keypair + `pending` registration only; (b) admin approve/revoke + device-scoped sessions + instant logout; (c) command channel and desired state; (d) per-device config. |
| W6 | Vue admin at `/console/` (§5) | yes | M–L | Flutter admin ≈5k lines; `orders_view.dart` (1.4k) is the big screen. It uses the root admin API and v1-framed `/ws` unchanged, so **it needs no `/v2`** (D1). The admin image gains a Node build stage; the Flutter admin stays at `/` in the same nginx image during the overlap. Node 26 is available locally. |
| W7 | Drop the Windows client (housekeeping) | yes | S | Decided (D1): IMPLEMENTATION_PLAN TH.3. |

### 11.2 Android 11 specifics that shape the design

- **No silent self-update on API 30.** `PackageInstaller` sessions work with
  `REQUEST_INSTALL_PACKAGES` plus the per-app "install unknown apps" grant, but every update
  shows a system confirmation. Updates without that prompt (`USER_ACTION_NOT_REQUIRED`) start at
  API 31. Device-owner mode also allows silent installs, but it can only be set over `adb` on a
  device without accounts. It is therefore a device-day-only decision (delta Q15).
- **The updater must not depend on login.** If a v2 build ships with broken login or token
  handling, the update check has to keep working, or the fleet is stuck until the next device
  day. So `/v2/client/latest` and the APK download should not require a user token: public, or
  device credential once W5(b) exists (delta Q5). Run the update check first at app start,
  before anything else can fail.
- **Identity is permanent.** The `applicationId` and the signing key can never change for OTA
  updates. v1 is `com.example.frontend`, so pick a real ID for v2 and back up the keystore
  outside the repo before the first release build (delta Q18).
- **Target vs min SDK.** "Android 11" fixes **`minSdk = 30`**. Set `targetSdk` to the current SDK;
  it changes behaviour only on newer Android versions and costs nothing on Android 11.
- **Token storage.** Jetpack Security's `EncryptedSharedPreferences` is deprecated. Use an
  Android Keystore AES key around DataStore (no extra library), or Tink. The device identity
  keypair also lives in the Keystore.
- **Updates on a schedule.** `WorkManager` periodic work has a 15-minute floor and is deferred
  by Doze. Combined with checks at start and on resume, that is enough. The forced path is the
  426 answer (§3.4).

### 11.3 Device-day risk and how to reduce it

0. Rehearse only with the **signed release APK**, never a debug build. v1 shows why: its release
   build had no network and nobody noticed, because only debug builds were ever run
   (KNOWN_LIMITATIONS #10).
1. Rehearse OTA end to end **before** the day on an Android 11 (API 30) emulator image: install
   build N, publish N+1 through `scripts.publish_client_release`, update, then do the same from
   a build with login disabled. This shows the updater works without a session.
2. Keep the updater a small, separate module with its own tests (version compare, SHA-256
   check, rejection of a wrong hash, 426 handling).
3. On the day: install v2 over `adb` (needs USB debugging) or from the backend download URL in
   the device browser. Then grant "install unknown apps" (Settings, or
   `adb shell appops set <id> REQUEST_INSTALL_PACKAGES allow`), log in once, and run one real
   update to a dummy build.
4. Record per device: model, Android version, Google Play services yes/no (Play Protect can warn
   on sideloaded APKs), scanner suffix (Enter or Tab), and whether the scanner offers an intent
   API.

### 11.4 Backend notes for planning

- **Instant revocation without Redis.** `get_current_user` already loads the user row on every
  request (SYSTEM_REFERENCE §5). A session row checked in PostgreSQL in the same step gives
  instant logout with no fail-open question when Redis is down. With two devices the cost is
  nothing (delta Q19).
- **`sid` rollout:** optional in `jwt.decode` (`require` list) during the first refresh TTL
  (§10.6).
- Migrations are all additive (`auth.devices`, `refresh_tokens.device_id`, a session id). No drops,
  so nothing needs the "ask before dropping" rule.
- **v2 must be shown sensibly to v1 (§3.3):** parity first, no new order states or meanings in
  the first v2 releases.
- **Release placement:** `v0.5.0` is already tagged on `master` (`398d6fd`, 2026-11-22). The `/v2`
  backend therefore ships in **v0.6.0** at the earliest. §7's question is moot, and so is
  V2-2's "in v0.5.0" (delta Q3). Local `dev` (`c1e03dc`) is behind that release merge commit.

---

## 12. Client identity, signing and developer verification (guide, Q18)

Decided (delta D2): `applicationId` **`com.bakingholic.orderchecker`**; you hold the keystore.
When implemented, the publishing steps move to RELEASE.md and OPERATIONS.

### 12.1 What is permanent

| Thing | Can it change? | If lost or changed |
|---|---|---|
| `applicationId` | never | the device treats it as a different app; reinstall by hand |
| Release signing key | never (practically) | updates refuse to install; the package can't be registered with Google (§12.6); reinstall by hand on every device |
| `versionCode` | only upwards | Android refuses downgrades; the updater compares it |
| Kotlin `namespace` (code package) | freely | nothing; it is not the app identity |

### 12.2 Generate the key (once, on your machine)

```bash
mkdir -p ~/keys/orderchecker && chmod 700 ~/keys/orderchecker
keytool -genkeypair -v \
  -keystore ~/keys/orderchecker/orderchecker-release.p12 -storetype PKCS12 \
  -alias orderchecker -keyalg RSA -keysize 4096 -validity 36500 \
  -dname "CN=Bakingholic Order Checker"
keytool -list -v -keystore ~/keys/orderchecker/orderchecker-release.p12 -alias orderchecker \
  | grep -E "SHA256:"
```

- PKCS12 uses **one password** for the store and the key. Generate a long random one in your
  password manager.
- The SHA-256 certificate fingerprint is **public**. Record it in RELEASE.md: it identifies the
  right key in a backup, and Google registration asks for it (§12.6).
- `keytool` comes with the JDK (JBR 25 or system JDK 27, both present).

### 12.3 Back it up (before the first release build)

1. Password manager: an entry with the password, the alias, the fingerprint, and the keystore
   file attached (or `base64 orderchecker-release.p12` pasted as a note).
2. Offline copy: the `.p12` file on a USB stick kept away from the computer, with the password
   written separately.
3. **Restore test:** copy the backup into a temp folder and run `keytool -list` on it with the
   password. Compare the fingerprint.
4. Never in the repo. Add `*.p12`, `*.jks`, `*.keystore` and `keystore.properties` to
   `.gitignore` in the new app's directory.

### 12.4 Gradle wiring (written in the plan's W3 task; shown here for review)

`frontend/client-android/keystore.properties` (git-ignored, on your machine only):

```properties
storeFile=/home/<you>/keys/orderchecker/orderchecker-release.p12
storePassword=<password>
keyAlias=orderchecker
keyPassword=<same password>
```

`app/build.gradle.kts`, reading the file locally or environment variables in CI (§12.7):

```kotlin
import java.util.Properties

val signing = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}
fun secret(key: String, env: String): String? = signing.getProperty(key) ?: System.getenv(env)

android {
    namespace = "com.bakingholic.orderchecker"
    defaultConfig {
        applicationId = "com.bakingholic.orderchecker"
        minSdk = 30                      // Android 11 (MT67)
        targetSdk = 37                   // latest installed platform
        versionCode = providers.gradleProperty("oc.versionCode").get().toInt()
        versionName = providers.gradleProperty("oc.versionName").get()
    }
    signingConfigs {
        create("release") {
            secret("storeFile", "OC_KEYSTORE_PATH")?.let { storeFile = file(it) }
            storePassword = secret("storePassword", "OC_KEYSTORE_PASSWORD")
            keyAlias = secret("keyAlias", "OC_KEY_ALIAS")
            keyPassword = secret("keyPassword", "OC_KEY_PASSWORD")
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")   // no key → the build fails
            isMinifyEnabled = true
        }
        debug {
            applicationIdSuffix = ".debug"   // installs beside the release app on the spare device
            versionNameSuffix = "-debug"
        }
    }
}
```

- **Debug builds use the debug key and `com.bakingholic.orderchecker.debug`,** so they install
  beside the release app and can never be confused with it. A debug-signed APK can't update a
  release install.
- **Versions** live in `gradle.properties` (`oc.versionCode=1`, `oc.versionName=2.0.0`). Raise
  `versionCode` by 1 for every published APK, and never reuse one.
- Verify every release APK before publishing:
  `apksigner verify --print-certs app-release.apk` (from `build-tools/37.0.0`). The
  fingerprint must match the one recorded in RELEASE.md.

### 12.5 Updater checks that depend on the key

Before handing the file to `PackageInstaller`:

1. SHA-256 of the download equals `latest.json`'s `sha256`.
2. `PackageManager.getPackageArchiveInfo(path, GET_SIGNING_CERTIFICATES)`: same package name and
   the same signer digest as the installed app. `versionCode` is greater than the installed one.

Android enforces (2) itself, but checking first gives a clear error message instead of a
generic "App not installed".

### 12.6 Android developer verification (new, affects OTA)

Google now requires apps on **certified** devices (Google services present; the MT67 ships
with GMS) to come from a registered developer:

- **Since 2026-09-30** in Brazil, Indonesia, Singapore and Thailand, but only for installs from
  participating app stores. Sideloaded apps are not covered yet.
- **2027: global, for all apps on certified devices**, sideloaded ones included. After that,
  installs **and updates** of an unregistered app fail unless the device has the "advanced
  flow" enabled. `adb` installs stay exempt.

So the v2 self-updater works now, but **it stops working in 2027 unless the package is
registered**. Registration needs the package name plus the signing key's SHA-256 fingerprint,
and a lost key means the package can never be registered. Options (delta Q21):

| Option | Cost / effort | Fit |
|---|---|---|
| **Register** in the Android Developer Console, full distribution | $25 once; identity check (individual: ID; organization: D-U-N-S number + verified website) | **Recommended.** OTA keeps working everywhere, with no per-device setup. Do it soon after generating the key. |
| Limited distribution account | free; device cap 20–50 (Google's pages disagree); devices enrolled by QR + consent | Meant for students, hobbyists and personal use ("no commercial intent"). A business tool probably doesn't qualify. |
| Enable the **advanced flow** on each device | free; developer mode, a restart, a **24-hour wait**, then PIN/biometric confirmation; can be set "indefinitely" | Fallback only: Google may change it, and it shows a warning on every unverified install. Start it the day *before* the device day if you use it. |
| Managed devices + organization store | MDM / device owner | Exempt, but this is the device-owner route you declined for round 1. |

Sources: developer.android.com/developer-verification (guides, FAQ, limited distribution),
read 2026-11-22.

### 12.7 CI signing (later, when you test it)

- GitHub secrets: `OC_KEYSTORE_B64`, `OC_KEYSTORE_PASSWORD`, `OC_KEY_ALIAS`, `OC_KEY_PASSWORD`.
- A separate workflow that runs only on tags or manual dispatch, inside a GitHub **environment**
  with a required reviewer (you). Never on pull requests.
- The step decodes the keystore into `$RUNNER_TEMP` and sets `OC_KEYSTORE_PATH`. The build reads
  it through `secret(...)` above. Upload the signed APK as an artifact, and publish it to the
  server by hand.
- Trade-off: GitHub then holds a third copy of the key. Signing locally (default until you test
  CI) avoids that.
