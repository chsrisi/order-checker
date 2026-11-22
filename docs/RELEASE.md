# Release runbook

How a backend + admin release reaches production. Branch model: feature branches →
`dev` → release PR → `master` + tag `vX.Y.Z` (docs/archive/BRANCH_SPLIT_REVIEW.md §4.1).
Production is not strictly uptime-sensitive, so short maintenance windows are fine
(KNOWN_LIMITATIONS #8). The operator client is **not** part of a release: it keeps
working as long as contract v1 holds.

## 1. Release PR checklist (`dev` → `master`)

- [ ] CI green: backend (incl. contract v1 + PostgreSQL), migration gate, both Flutter apps,
      `android (client-android)`.
- [ ] **Contract v1 sign-off.** `backend/tests/contracts/client_v1.json` is unchanged, or
      every change is additive and explained in the PR (e.g. T2.14 length limits). WS frames
      still carry `data` as a list of objects, and the WS handshake still rejects with 403.
- [ ] `backend/pyproject.toml` version bumped (SemVer); `uv lock` and
      `uv export --format requirements.txt --no-hashes --no-dev -o requirements.txt` run (the
      command CI uses; CI ignores `#` lines when comparing).
- [ ] New migrations reviewed by hand: schema-qualified, with a working `downgrade()`.
- [ ] Docs updated: API.md, OPERATIONS.md, KNOWN_LIMITATIONS.md, this file (if the window
      needs special steps).
- [ ] Release notes list anything operators notice (relogin, new admin features).

After merge: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z` (maintainer).

## 2. Maintenance window (every release)

1. **Announce** the window to operators. Ask them to finish open picks and scans.
2. **Back up** (keep for at most 90 days, ideally 30; see OPERATIONS "Data Retention"):
   ```bash
   cd backend
   docker compose exec -T db pg_dump -U postgres -Fc bakingholic > backup-$(date +%F).dump
   docker compose exec -T redis sh -c 'REDISCLI_AUTH="$(cat /run/secrets/redis_password 2>/dev/null)" redis-cli SAVE'
   tar czf keys-$(date +%F).tgz data/keys
   ```
   (Before v0.4.0, Redis has no password, so the `REDISCLI_AUTH` part is empty and still works.)
3. **Deploy:**
   ```bash
   git fetch --tags && git checkout vX.Y.Z
   docker compose -f compose.yaml -f compose.prod.yaml up -d --build
   docker compose -f compose.yaml -f compose.prod.yaml logs -f server   # migrations + "startup_config_accepted"
   ```
   If startup is refused, the log lists every configuration problem (OPERATIONS
   "Environment Profiles"). Fix them and run `up -d` again.
4. **Smoke test:**
   - admin web: log in, see users, orders, and stock
   - a test operator on the client: log in, sync orders, claim one, add a pick, scan a label
   - admin: close the test label (or use a synthetic one)
5. **Tell operators** to tap *retry* on the connection banner, or to log in again if the release
   notes say so.

## 3. Rollback

1. `git checkout <previous tag>`
2. If the new release added migrations, run `docker compose exec server alembic downgrade <previous head revision>` **before** switching code. Each release note names the revision.
3. `docker compose ... up -d --build`
4. If the token identity (`APP_ENV`, `JWT_AUDIENCE`, `JWT_ISSUER`) or the keys differ between the two versions, operators log in again.
5. If data must be restored: `pg_restore -U postgres -d bakingholic --clean backup-<date>.dump`, then restore `data/keys` (a database restore without the keys forces a relogin) and the Redis volume (it holds the Shopee tokens).

## 4. Operator app (v2) signing key

The Android app's release key is permanent (V2_SPEC §12.1). Generate and back it up as in
V2_SPEC §12.2–12.3. Its SHA-256 certificate fingerprint is public: record it here once, and
compare every release APK against it (`apksigner verify --print-certs <apk>`, the
`Signer #1 certificate SHA-256 digest` line). A mismatch means the wrong key: do not publish.

<!-- Paste the output of: keytool -list -v -keystore <p12> -alias orderchecker | grep SHA256:
     (keytool prints it with colons; apksigner prints it without; both are the same value) -->
- Release key (alias `orderchecker`, generated YYYY-MM-DD): `SHA256: <paste fingerprint>`

## 5. Release-specific windows

### v0.4.0: first production-rules release (IMPLEMENTATION_PLAN T3.6)

This window **logs every device out once**. The token identity changes from
`*:v0.3a` to `*:production` (T3.1), and production moves to the override file with Redis
auth. No schema migrations are added. Do the steps in this order.

**Before the window** (prepare on the server, nothing restarts yet):

1. Create the secret files in `backend/.secrets/` (`chmod 600`), as listed at the top of
   `compose.prod.yaml`:
   - `redis_password`: a new long random value
   - `redis_url`: `redis://:<redis_password>@redis:6379/0`
   - `admin_password`: a long random value. **It must not be `admin`** or startup refuses.
     For an existing admin account it is applied with `scripts.set_admin_password` (see below).
   - `database_url` and `partner_key`: move them out of `.env`
2. Edit `backend/.env`, using `.env.production.example` as the reference:
   - add `APP_ENV=production`
   - **remove** `JWT_VERSION`, `JWT_AUDIENCE`, `JWT_ISSUER` and `API_VERSION`. Left in place,
     they pin the old identity or are ignored with a warning.
   - set `CORS_ORIGINS=` (empty) and remove `CORS_ORIGIN_REGEX`
   - replace `SINGLE_LOCATION_STOCK_BYPASS=…` with `STOCK_LOCATION_MODE=multi|single`
   - make sure `MOCK_ORDER_BYPASS=0`, and that `ALLOW_REGISTRATION` is unset or `0`
   - remove `DATABASE_URL`, `PARTNER_KEY` and `ADMIN_PASSWORD` (now file secrets)
3. Check that `docker compose version` reports v2.24.4 or later.

**In the window:** follow §2. The deploy command is
`docker compose -f compose.yaml -f compose.prod.yaml up -d --build`. Redis restarts with
a password on the same data volume, so the Shopee tokens survive. Then:

- Every operator logs in again (this is expected).
- New operator accounts are created in the admin app (**Users → New operator**). Self-registration
  now returns 403.
- PostgreSQL and Redis ports are no longer published. Use `docker compose exec db psql …`
  for maintenance.

**Admin password.** `seed_admin_user` creates the admin only if it is missing, and the
startup guard checks only the *configured* value. An admin created long ago therefore keeps
its old password until you apply the new one. **Run this once in the window, right after
deploy:**

```bash
docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.set_admin_password
```

It writes `.secrets/admin_password` to the existing admin, refuses placeholder values,
and revokes the admin's sessions.

### Step 4 (inventory integrity, T4.3/T4.4): shipped in v0.4.0

Done 2026-11-21: steps 4 and 5 shipped together with v0.4.0 (tag `v0.4.0` = `2081206`), and
the commands below were run then. Kept as the record of that window. This window shipped the allocation table and the structured stock log (migration
`b7c4e1a9d2f3`, down revision `d862d86e8707`). Per delta D5 / Q4:

1. Operators finish their open picks before the window.
2. Back up and deploy as in §2. The migration adds the new table and columns. It folds duplicate
   `(sku, location)` stock rows into one, logged `migration_merge`, before the unique index is
   created. A downgrade keeps the folded rows.
3. Run the cutover command. It deletes the remaining open pick entries **without restoring
   stock** and writes one `cutover_clear` log row:
   ```bash
   docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.clear_open_pick_entries            # count only
   docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.clear_open_pick_entries --confirm
   ```
   If this step is missed, a legacy entry has no allocations, and deleting it restores nothing.
   Nothing is guessed.
4. If production runs `STOCK_LOCATION_MODE=single`, also run
   `python -m scripts.stock_merge_single --confirm` (OPERATIONS "Stock Location Mode").
5. Smoke test: pick 1 of an item, delete the entry, and check that the stock is back.

### v0.6.0: dual-contract backend, sessions, OTA (IMPLEMENTATION_PLAN step 6)

Migrations `d4a7e2c9b1f0` (sessions; deletes refresh tokens) and `e5b8f3a1c2d4` (devices,
additive). Rollback: `alembic downgrade c3f8a2d5e6b1`, then check out `v0.5.0`. Tokens issued
by v0.6.0 keep working on v0.5.0 (it ignores `sid`), so a rollback needs no second relogin.

**One relogin for everyone.** `auth.sessions` replaces the old refresh tokens and tokens
without the `sid` claim are rejected (V2_DELTA Q24). Each v1 device gets 401, fails its refresh
and shows the login screen; operators log in once. The admin web logs in again too.

1. Announce the window and the one-time relogin (§2 step 1).
2. Back up (§2 step 2).
3. Create the releases directory on the host, next to `data/keys`:
   `mkdir -p backend/data/releases/client` (mounted read-only into the container as
   `RELEASES_VOLUME`; OPERATIONS "Publishing a client release").
4. Deploy (§2 step 3). The log shows both migrations, then `startup_config_accepted`.
5. Publish the first v2 APK when it exists (step 6 device day, T6.16), from `backend/`:
   `uv run python -m scripts.publish_client_release <apk> --version-code 1 --version-name
   2.0.0 --dir data/releases/client --confirm`. Until then `GET /v2/client/latest` answers 404,
   which is expected.
6. Smoke test v1 on one device: log in (expect the relogin), sync, claim an order, add a pick,
   delete it (stock comes back), scan a test label.
7. Smoke test v2 from a laptop on the LAN:
   ```bash
   curl -s http://192.168.1.50:8000/v2/meta          # client_contract {"min":1,"max":2}
   curl -si http://192.168.1.50:8000/v2/client/latest | head -1   # 404 until step 5, then 200
   curl -si http://192.168.1.50:8000/v2/items/find?query=x | head -1   # 400: no X-Client-Version
   ```
8. Admin: *log out everywhere* on a test operator (`POST /admin/users/{username}/logout`), check
   that its device returns to the login screen within one request.

Release notes: one-time relogin; logout, password reset and the new "log out everywhere" take
effect immediately; the backend serves the v2 operator app (`/v2`, OTA updates, device
registration) next to the unchanged v1 app.

### v0.5.0: pre-release fixes (no relogin, no client change)

Migration `c3f8a2d5e6b1` (down revision `b7c4e1a9d2f3`) drops the never-used table
`orders.pick_item_entries_log`. v0.4.0 code never touches it, so a code rollback works without
the downgrade; `alembic downgrade b7c4e1a9d2f3` recreates the table empty.

1. Deploy as in §2. `up -d --build` rebuilds **both** the backend and the admin web image.
   When only the admin changed, see OPERATIONS "Rebuilding the Admin Web After a Code Change".
2. **Admin browsers, once:** v0.4.0 and earlier served `main.dart.js` and the other `.js`
   files as `immutable` for a year. Do a hard reload (Ctrl+Shift+R) or clear the site data in
   every browser that has opened the admin app. Without it, the browser keeps the old bundle.
3. Smoke test, in addition to §2:
   - admin → Inventory → *Export CSV* and Orders → scan export download a `.csv` file
   - delete a test operator that has a pick entry; its stock comes back (`pick_restore` in
     `warehouse.stocks_log`, actor = the admin)
   - `GET /stocks` answers 200 (it returned 500 without `?join_warehouse=true` before)

Release notes: admin CSV exports work on the web; deleting an operator restores the stock of
its open picks; `GET /stocks` fixed; the admin web is no longer stuck on a cached build.
