# v2: decision delta

This file records decisions made after [V2_SPEC.md](V2_SPEC.md), the "spec" (proposal, code
verification §10, feasibility §11). Where the two disagree, **this file wins**, and later rounds
win over earlier ones. Earlier rounds are not edited: a later round supersedes them.

**Nothing here is implemented yet.** The tasks come next, as a new step in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), once the questions marked "before planning"
are answered. Implementation starts only on the maintainer's go-ahead.

Legend:

- ~~struck~~: answered or superseded
- **✅** decided
- **⚠️ revisit**: decided, but there is a follow-up for the maintainer
- **❓ open**: not answered yet; the stated recommendation is the working default
- **📌 kept**: kept for reference, no action

---

## Delta 1 (2026-11-22)

### D1.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| Ops | **Two operator devices work at the same time.** The one backend process serves both, so "no multi-worker" (= one Uvicorn process) stands (spec §1, §10.1). | ✅ |
| V2-2 | **Drop the Windows operator client** as housekeeping, not tied to the v2 client. Becomes IMPLEMENTATION_PLAN **TH.3**. | ✅ |
| V2-3 / Q4 | The Vue admin is served at **`/console/`**, not `/admin/`. `/admin/*` stays the admin API, proxied by nginx as today. The Flutter admin stays at `/` until it retires (spec §10.3). | ✅ (supersedes V2-3's path) |
| V2-5 scope | `/v2` covers **what the operator client calls, plus the new device and OTA endpoints**. The admin API stays at the root, and so do the new admin endpoints for devices (`/admin/devices*`). The Vue admin uses root routes and v1-framed `/ws` (spec §10.2, §11.1 W6). | ✅ (narrows V2-5's "full surface") |
| APK host | **The backend serves the APK** and its metadata from a mounted volume, on the port the devices already use (spec §10.4, §11.1 W2). | ✅ |

### D1.2 Consequences

- **nginx:** add a `/console/` location (SPA fallback to `/console/index.html`; Vite assets are
  content-hashed, so `/console/assets/` can be cached `immutable`). **No `/v2` proxy is needed**,
  because the Vue admin does not call `/v2` and the client bypasses nginx.
- **Admin image:** a Node build stage is added beside the Flutter one, and one nginx serves
  both apps during the overlap.
- **`/v2` router:** registers the client operations one by one (`routers/v2/`). Whole routers are
  not re-included, because that would mirror admin operations (spec §11.1 W1). No register
  endpoint (the client v2 backlog drops the Register button).
- **TH.3 (Windows):** delete `frontend/client/windows/`. Update KNOWN_LIMITATIONS #7 and #8,
  SYSTEM_REFERENCE §1/§2/§12.1, ARCHITECTURE "Frontends", README, TESTING if needed. Run
  `flutter analyze && flutter test` in the client. Not tied to a v2 release.
- **Docs to correct when the v2 plan step is written:** KNOWN_LIMITATIONS #8 and
  IMPLEMENTATION_PLAN §5 still state A-5 ("`/v2` only for changed operations"). V2-5 + D1
  supersede it.

---

## Delta 2 (2026-11-22)

### D2.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| Q1 | Devices are **Newland MT67** (Android 11 with GMS, per Newland's datasheet). The scanner is set to **"simulate keystroke"** output, i.e. keyboard wedge. | ✅ |
| Q15 | **No device-owner mode** in the first round. | ✅ |
| Q16 | You own the devices: USB debugging and `adb` are available. Google Play services are present on the MT67 (see D2.2 on developer verification). | ✅ |
| Q17 | Rehearse OTA on **both** the API 30 emulator and the spare handset. | ✅ |
| Q18 | `applicationId` **`com.bakingholic.orderchecker`**. You generate and hold the keystore; the guide is spec §12. CI signing is tested later (spec §12.7). Sign locally until then. | ✅ (⚠️ CI later) |
| Q6 | Analysis requested: [V2_SERVER_ADDRESS.md](V2_SERVER_ADDRESS.md). It recommends option **C** (domain via Cloudflare Tunnel as primary, LAN as fallback, introduced in stages; LAN only on the device day). | ❓ awaiting decision |

### D2.2 Consequences

- **Scanner input (W4):**
  - v2 starts with keyboard wedge, exactly like v1: a focused field, submit on the Enter suffix.
  - Newland also offers an **API (broadcast) output mode**: action `nlscan.action.SCANNER_RESULT`,
    extra `SCAN_BARCODE1`. That frees the UI from focus handling, but it needs a scanner
    setting changed on each device.
  - Keep it as a later, optional input path. Before relying on it, check the action and extra
    names on an MT67, because Newland documents them for its PDA family rather than for this
    model.
  - Record the wedge suffix (Enter or Tab) on the spare device.
- **Google services present → Android developer verification applies** (spec §12.6). OTA
  self-updates work today. Once enforcement goes global in 2027, they need the package
  registered with Google, or the per-device "advanced flow". New question **Q21**.
- **Play Protect** may warn on the first sideload, so expect an "install anyway" tap on the
  device day. Rehearse it on the spare device (Q17).
- **Device-day install path:** `adb install` (exempt from verification), then grant "install
  unknown apps" over `adb shell appops`. The browser-download path is not needed.
- **Q6 interim:** whichever way Q6 goes, the device-day build uses the LAN profile
  (`http://192.168.1.50:8000`). The configurable server profile (spec §4.5) is in the first
  build either way.

---

## Delta 3 (2026-11-22)

### D3.1 Decisions and corrections received

| Ref | Decision | Status |
|---|---|---|
| Q6 (fact) | **v1 runs on the devices as a Flutter debug build**; the LAN IP works only there. Cause found: the release manifest lacks the `INTERNET` permission (KNOWN_LIMITATIONS #10). The LAN IP and the cleartext rule are fine, so option A/C's LAN path stands. | ✅ corrected |
| Q7 | `frontend/client-android/` (Kotlin) and `frontend/admin-web/` (Vue). | ✅ |
| Q9 | Device credential = **device token** issued at enrollment, hashed in `auth.devices`, revocable per row. | ✅ |
| Q11 | **No local JWKS verification** in the v2 client; it reads `exp` only to decide whether to refresh first. | ✅ |
| Q12 | Android dependencies approved: Kotlin, Compose (BOM), AndroidX Activity/Lifecycle/Navigation, OkHttp, kotlinx.serialization, DataStore, WorkManager. Retrofit optional. No Firebase or Play services. | ✅ |
| Q13 | Vue dependencies approved: Vue 3, Vite, Vue Router, Pinia, Naive UI, `openapi-typescript` (build-time). | ✅ |
| Q14 | Typed clients are generated from **committed OpenAPI files** per surface (`backend/openapi/v2.json`, `admin.json`), checked against `app.openapi()` by a test. | ✅ |
| Relogin | **An operator relogin is cheap** (maintainer). Planned relogin windows are acceptable when they make the design simpler. | ✅ |

### D3.2 Q19: session store, PostgreSQL vs Redis

**Refresher: what Redis keeps, and why nothing has been lost so far**

- **Production Redis persists to disk.** It runs `redis-server --appendonly yes` on the named
  volume `redis-data` (`compose.prod.yaml`). Every write goes to the append-only file, which
  is fsynced every second by default.
- A container restart, a host reboot or a power cut reloads that file, so the data comes back.
  A power cut loses at most the last second of writes. The base `compose.yaml` (dev) has no
  `--appendonly` and falls back to Redis's periodic snapshots.
- So Redis restarts *have* happened (every power outage), and they lost nothing because of
  the append-only file, not by luck.
- What lives there (SYSTEM_REFERENCE §4.4):
  - **Shopee access/refresh tokens**, with no TTL. This is the one valuable item.
  - WS tickets (30 s), Shopee-config unlock tokens (120 s), login-failure counters, the
    last-seen egress IP.
- **Shopee tokens if the volume were lost:** `ShopeeTokenManager.get_token` falls back to the
  configured `SHOPEE_ACCESS_TOKEN`/`SHOPEE_REFRESH_TOKEN` and re-seeds Redis. Those configured
  values are the original ones and are probably stale, because Shopee rotates tokens on
  refresh.
- The first refresh then fails, the circuit trips, and Shopee calls answer 503 until an admin
  saves fresh tokens in **Config**. Sessions or relogins would not be the problem.
- Backups: RELEASE/OPERATIONS already list the `redis-data` volume (OPERATIONS "Backups" item
  2), separately from `pg_dump`.

**Weighing**

| Criterion | PostgreSQL session rows | Redis active-session keys |
|---|---|---|
| Per-request cost | **≈0.** `get_current_user` already loads the user row on every request (sync `def`, threadpool), and the session check joins into that same query. | One extra round trip. The Redis client is **async**, while `get_current_user` is a sync `def`, so it needs either an async rewrite of the dependency or a second, sync Redis client. |
| Redis unavailable | not involved | Choose **fail-open** (revocation silently off, like the login throttle) or **fail-closed** (every request 401, everyone logs in again after Redis returns). |
| Consistency | Same transaction as user deletion, password reset and device revoke, so no window where the user is gone but the session is alive. Matches the unit-of-work rule (SYSTEM_REFERENCE §3). | A second source of truth beside `refresh_tokens` (which is in PostgreSQL), so two writes in two systems for every login, refresh and revoke. |
| Durability / backups | In `pg_dump`, restored with everything else. | AOF volume, a separate backup item. Loss = a relogin, which is cheap (D3.1). |
| Admin "sessions per device" view, audit (`ip_address`, `agent`, `last_seen`) | A SQL query; finally writes the columns that are never written today (§14.3). | Needs key scans or secondary sets. |
| Expiry cleanup | Rows are deleted by the existing hourly `REFRESH_CLEANUP` task. | Native TTL. |
| Write load | `last_seen_at` throttled to one update per minute per session (nothing at two devices). | Cheap writes. |
| Multi-process readiness | Shared already. | Shared already. |

**Recommendation: PostgreSQL.** Cheap relogins take away Redis's main drawback (losing data),
but the fail-open/fail-closed choice, the second source of truth and the async/sync mismatch
remain. Redis would only win for speed at a scale this system doesn't have.

**Sketch for the plan:**

- `auth.sessions`: `id` (= `sid`), `username` FK, `device_id` FK nullable, `created_at`,
  `last_seen_at`, `revoked_at`, `ip_address`, `agent`.
- `refresh_tokens.session_id` FK with `ON DELETE CASCADE`. Rotation keeps the `session_id`.
- Access and refresh tokens carry `sid`.
- `get_current_user` loads the user and the live session in one query. Missing or revoked
  session → 401.
- Revocation: delete the session (which cascades to its refresh rows) and close its sockets
  (code 1008).

**`sid` rollout (new Q24):** since relogins are cheap, make `sid` **required** right away and
let every operator log in once in that release's window (RELEASE.md, like v0.4.0). That avoids
a 24 h "tokens without `sid`" grace path in the code. v1 then turns the 401 into a failed
refresh and the login screen (spec §10.6).

---

## Delta 4 (2026-11-22)

### D4.1 Decisions received

| Ref | Decision | Status |
|---|---|---|
| Q3 | The `/v2` backend ships in **v0.6.0**. | ✅ |
| Q5 | `/v2/client/latest` and the APK download need **no user token**. They are public at first and get a device credential after W5(b). Metadata is `latest.json` beside the APK, written by `scripts.publish_client_release`. | ✅ |
| Q19 | Sessions live in **PostgreSQL** (`auth.sessions`, D3.2). | ✅ |
| Q24 | `sid` is **required at once**, with one planned operator relogin in the v0.6.0 window. | ✅ |
| Q10 | Instant revocation for v1 too: **yes, by design** of Q19 + Q24 (D4.2). | ✅ |
| Q23 | **Skip** the v1 release-build fix; v1 stays as it is until it retires. | ✅ |
| Q6 | **Option C** ([V2_SERVER_ADDRESS.md](V2_SERVER_ADDRESS.md)). Focus on **stage 1** (LAN) now; stage 2 is a maintainer runbook for later (that file, §7). | ✅ |
| Q6a / Q6b | Device hostname behind an **Access service token**; admin hostname behind **Access with e-mail one-time PIN**. | ✅ |
| Q6c | You configure the hostnames. The docs use the template `api.<domain>` / `ops.<domain>`. | ✅ |
| Q6d | Sync averages **4–5 s** (rarely more or less), far below Cloudflare's ~100 s. A review of the sync flow and its optimizations is pinned (Q25). | ✅ |
| Q6e | `192.168.1.50` is outside the DHCP range: effectively static. | ✅ |
| Q8, Q20, Q21 | Pinned for later: retirement criteria (Q8 default accepted as a draft), pilot order, Google developer registration. | 📌 |

### D4.2 Q10: why Q19 + Q24 give it for free, and the conditions

- Every v1 request already goes through `get_current_user`. Once that query also requires a
  live session row, a revoked v1 session gets **401 on its next request**.
- v1 then tries one refresh. The refresh token belongs to the same session, and its row was
  removed by the cascade, so the refresh fails too. v1 logs out to the login screen (spec
  §10.6).
- Because `sid` is required at once (Q24), there are no tokens without a session left to slip
  through.
- **Conditions the implementation must meet:**
  1. A revoke deletes the session and its refresh rows **in one transaction**.
  2. It closes that session's open sockets (code 1008). A socket is authenticated only at the
     handshake, so without this a v1 device keeps receiving live updates. Today
     `ConnectionManager` keys sockets by username; per-session closing needs the `sid` stored
     per socket at the handshake. The WS ticket must then carry the `sid`, not just the
     username.
  3. When v1 reconnects, the new ticket request fails with 401 → refresh fails → logout. That
     is v1's existing path.
- **v1 granularity:** v1 sessions have `device_id = NULL`, so for v1 the admin action is "log
  out this user everywhere". Password reset and user delete already do that, and become instant
  with this change.

### D4.3 Status

Every question marked "before planning" is answered. Next step in the flow: write the v2 step
(v0.6.0) in IMPLEMENTATION_PLAN.md, on your go-ahead.

**Plan written (2026-11-22):** IMPLEMENTATION_PLAN.md steps 6–8, with planning defaults P-9 to
P-21 (veto before step 6 starts) and the decision coverage in §6.1. Implementation starts on
your go-ahead, beginning with T6.0.

---

## Open questions and things to revisit

"When" says by when an answer is needed: **before planning** (the plan step can't be written
without it), **before device day** (it decides what the first APK must contain), or **later**.

| Ref | Question | Working default (recommendation) | When | Status |
|---|---|---|---|---|
| Q1 | ~~Scanner model / delivery~~ | Newland MT67, keyboard wedge ("simulate keystroke"); Newland broadcast API optional later (D2.2) | – | ✅ |
| Q2 | ~~Number of devices~~; device-owner/MDM possible? | Two devices (D1). MDM: see Q15. | – | ✅ / Q15 |
| ~~Q3~~ | ~~Release for the `/v2` backend~~ | v0.6.0 (D4) | – | ✅ |
| ~~Q4~~ | ~~Admin API vs static path~~ | `/console/` (D1) | – | ✅ |
| ~~Q5~~ | ~~Update endpoints: auth? metadata?~~ | No user token; `latest.json` beside the APK (D4) | – | ✅ |
| ~~Q6~~ | ~~Client server address~~ | Option C, stage 1 now; stage 2 runbook in V2_SERVER_ADDRESS §7 (D4) | – | ✅ |
| ~~Q7~~ | ~~Directory names~~ | `frontend/client-android/`, `frontend/admin-web/` (D3) | – | ✅ |
| Q8 | Criteria and date for retiring v1 and the Flutter admin | Draft accepted: v1 retires after both devices run v2 for 2 weeks with no fallback; the Flutter admin after every screen is ported and used for 2 weeks; then one major backend release removes v1. | later | 📌 |
| ~~Q9~~ | ~~Device credential~~ | Device token issued at enrollment (D3) | – | ✅ |
| ~~Q10~~ | ~~Instant revocation for v1~~ | Yes, by design of Q19 + Q24; conditions in D4.2 | – | ✅ |
| ~~Q11~~ | ~~Local JWKS verification in v2~~ | Dropped (D3) | – | ✅ |
| ~~Q12~~ | ~~Android dependencies~~ | Approved list (D3) | – | ✅ |
| ~~Q13~~ | ~~Vue dependencies~~ | Approved list, Naive UI (D3) | – | ✅ |
| ~~Q14~~ | ~~Typed client source~~ | Committed OpenAPI files per surface (D3) | – | ✅ |
| ~~Q15~~ | ~~Device-owner mode on device day~~ | No, first round (D2) | – | ✅ |
| ~~Q16~~ | ~~USB debugging / Google Play services~~ | Owned devices, `adb` available; GMS present (D2) | – | ✅ |
| ~~Q17~~ | ~~Rehearsal target~~ | Emulator **and** spare handset (D2) | – | ✅ |
| ~~Q18~~ | ~~`applicationId` and keystore~~ | `com.bakingholic.orderchecker`; your keystore; guide spec §12 (D2) | – | ✅ (⚠️ CI signing later, §12.7) |
| ~~Q19~~ | ~~Session store~~ | PostgreSQL (D3.2, D4) | – | ✅ |
| Q20 | Pilot order | Move one device to v2 first; the second follows after a full day on v2 without falling back. | later | 📌 |
| Q21 | Google developer registration before the 2027 global enforcement (spec §12.6) | Register the package (full distribution) once the key exists; fallback: the per-device advanced flow. | before 2027 | 📌 |
| Q22 | Newland broadcast scan API (`nlscan.action.SCANNER_RESULT`) | Later and optional; verify the names on the spare MT67 first. Wedge stays the default. | later | 📌 |
| ~~Q23~~ | ~~Fix the v1 release build~~ | Skip (D4) | – | ✅ |
| ~~Q24~~ | ~~`sid` rollout~~ | Required at once, one planned relogin (D4) | – | ✅ |
| Q25 | Review the Shopee sync flow and its optimizations (4–5 s today, on the request path) | Later: trace `sync_shopee_orders` end to end (SYSTEM_REFERENCE §7.1), measure each stage, and weigh moving it off the request path (backlog). | later | 📌 |
