# v2 discussion: how devices reach the server (LAN IP vs domain)

Status: **decided: option C** ([V2_DELTA.md](V2_DELTA.md) D4, 2026-11-22). Stage 1 (LAN) is
what v0.6.0 builds. Stage 2 is the maintainer's runbook in §7, to do later. Q6a–Q6e are
answered in D4. Nothing here is implemented yet.

---

## 1. Today

| Fact | Where |
|---|---|
| v1 bakes `BASE_URL`/`WS_URL` into each build; production devices use the LAN IP `192.168.1.50`, port `8000`, plain HTTP. | `frontend/client/.env.example`, KNOWN_LIMITATIONS #8 |
| v1 allows cleartext **only** for that IP literal (Android blocks cleartext by default since API 28). The IP-literal exception works on the devices today. | `frontend/client/android/app/src/main/res/xml/network_security_config.xml` |
| **The devices run a v1 *debug* build.** Release builds have no network access because the main manifest lacks `android.permission.INTERNET`; Flutter's template declares it only in `src/debug` and `src/profile`. A misconfiguration, not an Android limit: the cleartext rule above sits in `main` and works. (delta D3, KNOWN_LIMITATIONS #10) | `frontend/client/android/app/src/{main,debug,profile}/AndroidManifest.xml` |
| The client talks to Uvicorn directly; only the admin browser goes through nginx (`:3000`). | `backend/compose.yaml`, spec §10.4 |
| Tokens do not depend on the host: `iss`/`aud` come from `APP_ENV`, not from the URL. | SYSTEM_REFERENCE §5 |
| Shopee sync needs the internet anyway. Without it, picking already-synced orders, outbound scans and stock still work; claiming a new order (acquire 404 → sync) fails. | SYSTEM_REFERENCE §7.1–7.2 |

---

## 2. Options

- **A. LAN IP only**, as v1.
- **B. Domain only**, through a Cloudflare Tunnel (HTTPS from Cloudflare, no inbound ports).
- **C. Domain as the main address with the LAN as fallback, introduced in stages** (recommended,
  §4).
- *D. Split-horizon DNS: the same name resolves to the LAN IP inside the warehouse, with a real
  certificate on the server (e.g. Caddy + DNS-01 via the Cloudflare API).* One URL and HTTPS
  everywhere, but it adds a local reverse proxy, certificate renewal and router DNS overrides.
  Not worth it for two devices now; noted for later.

All of them are **feasible**. The client side costs the same in every case: a configurable
server address instead of a baked one (needed anyway, spec §4.5).

### 2.1 Weighing

| Criterion | A. LAN only | B. Domain only | C. Domain + LAN fallback |
|---|---|---|---|
| Works during an internet or Cloudflare outage | ✅ partly (no Shopee sync) | ❌ nothing works | ✅ falls back to LAN |
| Works away from the warehouse Wi-Fi (OTA anywhere, a device taken home) | ❌ | ✅ | ✅ |
| Transport security | ❌ plain HTTP: tokens and passwords readable by anyone on the Wi-Fi who can sniff | ✅ HTTPS to Cloudflare; Cloudflare → server inside the tunnel | ✅ on the domain; LAN path still plain HTTP |
| Exposure to the internet | none | API and admin login reachable by anyone (§3.1) | same as B |
| Survives a server IP change without touching devices | ❌ | ✅ | ✅ (fallback entry needs an update) |
| Survives moving the server to another machine or site | ❌ | ✅ | ✅ |
| New infrastructure and third-party dependency | none | cloudflared container, Cloudflare account, domain | same as B |
| Request limits added | none | ~100 s to first response byte, WebSocket idle timeout (§3.3) | same, on the domain path |
| Customer data through a third party | no | yes: order payloads with recipient names pass through Cloudflare (TLS ends there) | yes, on the domain path |
| Client complexity | lowest | low | + one fallback rule (§4.2) |
| Device-day risk | lowest (known to work) | needs the tunnel live and tested first | none if stage 1 is LAN (§4.1) |

---

## 3. Implications of a domain (B and C)

### 3.1 Exposure and how to contain it

What already protects the API: production startup rules, login throttle (10 failures per
username → 429 for 15 min), registration off (403), request size limits, API docs off, admin
creation impossible through the API. Not enough on its own for an internet-facing admin login.

Recommendation: **two hostnames**, both through the same tunnel.

| Hostname | Goes to | Protection |
|---|---|---|
| `ops.<domain>` | admin-web nginx (Flutter admin at `/`, Vue at `/console/`, admin API via its proxy) | **Cloudflare Access** with a browser login (e.g. one-time PIN to your e-mail). Nobody reaches the admin login page without passing Access first. |
| `api.<domain>` | Uvicorn `:8000` (what the devices use) | **Access service token**: the app sends `CF-Access-Client-Id`/`CF-Access-Client-Secret` on every request, including the WS upgrade. Anything without it is stopped at Cloudflare. |

Service-token notes:
- The token is in the APK, so anyone holding the APK has it. The APK download is behind the same
  token, so that circle stays "our devices".
- Choose a **non-expiring** duration (offered by Cloudflare, confirm in the dashboard), or set
  an expiry alert. An expired token cuts the domain path, updater included. The LAN fallback is
  the safety net (§4.2).
- Rotation: add the new token to the Access policy, ship an APK with it, remove the old token
  once both devices have updated.
- Alternative: leave `api.<domain>` open and rely on app auth plus a Cloudflare rate limit. It
  is simpler, but every probe on the internet reaches FastAPI. **Decide (Q6a).**

### 3.2 Backend changes

- A `cloudflared` service in `compose.prod.yaml`, outbound only. Its tunnel token is a file
  secret in `.secrets/`. The LAN port `8000` stays published for v1 (and the fallback).
- Client IPs: behind the tunnel every request comes from the cloudflared container. Logs lose
  the real IP unless Uvicorn runs with `--proxy-headers --forwarded-allow-ips=<cloudflared>` and
  the app reads `CF-Connecting-IP`. The login throttle is per username, so shared IPs cannot
  lock everyone out (P-4).
- No change to tokens, CORS (still same-origin for the admin), or contract v1.
- Bonus: HTTPS gives the admin browser a secure context, so the Flutter admin uses secure
  storage instead of its `localStorage` fallback (SYSTEM_REFERENCE §12.2).

### 3.3 Cloudflare limits to plan for

These come from Cloudflare's proxy documentation; check that they hold for Tunnel in your
account.

- **~100 s until the first response byte**, otherwise the client gets **524**. The only long
  call is `GET /shopee/orders?refresh=true` (synchronous Shopee sync). Check its real duration
  in the logs (`request_completed`, `duration_ms`, path `/shopee/orders`). If it approaches
  100 s, moving the sync off the request path (backlog) becomes necessary for the domain path.
- **WebSocket idle timeout (~100 s on non-Enterprise plans).** Uvicorn sends WS pings every 20 s
  by default (`--ws-ping-interval`), which should keep sockets open. Verify through the tunnel.
  Cloudflare edge restarts still drop sockets now and then; v2 reconnects with unlimited backoff
  (F-H8), so operators should not notice.
- Upload limits (100 MB on Free) do not matter: the only large file is the APK *download*.

### 3.4 v1 and the LAN

- v1 keeps `192.168.1.50:8000` until it retires. It cannot send service-token headers, so it
  can never use `api.<domain>` anyway.
- Give the server a **DHCP reservation** (or a static IP) so `192.168.1.50` never changes. This
  protects v1 today and the v2 fallback later.

---

## 4. Recommendation: C, in stages

### 4.1 Stages

| Stage | When | Device address profile |
|---|---|---|
| 1 | Device day | primary `http://192.168.1.50:8000`, no fallback. Nothing new to break on the day. |
| 2 | Tunnel live and tested from a laptop and the spare device | primary `https://api.<domain>` (+ service token), fallback `http://192.168.1.50:8000` |
| 3 | v1 retired | unchanged. The LAN port stays as fallback; it can be firewalled to the warehouse subnet. |

### 4.2 Client behaviour (one rule, kept small)

- The app stores a **server profile**: `primary`, optional `fallback`, optional service token.
  The build-time default is the stage-1 profile.
- **Active address** = the last one that answered. On a *connection* failure (DNS, TCP, TLS,
  timeout, Cloudflare 52x) the app tries the other one. It never switches on HTTP 4xx, because
  those are real answers. While on the fallback, it probes `GET /meta` on the primary every few
  minutes and moves back when it answers.
- **The updater always tries both**, so a broken tunnel or an expired service token never blocks
  an update while the device is on the warehouse Wi-Fi.
- A small status chip shows "LAN" when the fallback is in use.
- Cleartext stays allowed only for the LAN IP (same `network_security_config.xml` rule as v1).
- How profiles change: a hidden settings screen (admin PIN), the enrollment QR (§4A.2), and
  later pushed device config (§4A.5, W5(d)). No rebuild, **no relogin** (tokens do not depend on
  the host).

---

## 5. Example flows with the recommendation

**F1. Device day (stage 1).** Install v2, open it: the update check hits
`http://192.168.1.50:8000/v2/client/latest` and finds nothing newer. Log in, run one dummy
update. *Expect:* the same behaviour as v1 on the network side; no chip, because there is no
fallback.

**F2. Moving to the domain (stage 2).**
1. Create the tunnel and hostnames. Add `cloudflared` to the prod compose and deploy.
2. Test from a laptop: `curl https://api.<domain>/meta` with the service-token headers → 200;
   without them → blocked by Access. Open `https://ops.<domain>` → Access login, then the
   admin.
3. Test the spare device on mobile data (Wi-Fi off). Scan the stage-2 enrollment QR or enter the
   profile in the hidden settings, then pick and scan as usual.
4. Push the profile to both devices: QR or settings now, device config once W5(d) exists.
*Expect:* operators keep working without logging in again. The first request goes to the
domain. A few milliseconds more latency, which nobody will notice.

**F3. Normal day on the domain.** Everything goes through `api.<domain>`. WebSocket updates
arrive as now. *Expect:* an occasional silent WS reconnect after a Cloudflare edge restart.

**F4. Internet or Cloudflare down.** Requests to the domain fail at the connection level, the
app switches to the LAN within one request, and the chip shows "LAN". Picks, outbound scans and
stock work. Claiming an order that isn't synced yet fails because Shopee is unreachable (same
as today in an outage). When the internet returns, the `/meta` probe succeeds and the app moves
back. *Expect:* one slow request at the switch, then normal speed; the admin at `ops.<domain>`
is unreachable during the outage, while `http://192.168.1.50:3000` on the LAN still works.

**F5. Service token expired or revoked by mistake.** Cloudflare blocks the domain path (an HTTP
error from Access, not a connection error). Treat Access block pages as "unreachable" for the
switch rule, so the app moves to the LAN. The updater reaches the LAN too. Fix the token and
publish an APK with the new token if needed. *Expect:* the same as F4 until fixed.

**F6. Publishing an OTA update.** Run `scripts.publish_client_release <apk>` on the server.
Devices see it on their next start, resume or periodic check over either address, download,
verify the SHA-256, and show the Android install prompt. One tap per device (Android 11, spec
§11.2). *Expect:* the update works on-site or off-site.

**F7. Server moves to a new machine or site.** Point the tunnel at the new machine (tunnel
config only). Devices keep using `api.<domain>`. Update the fallback LAN entry through a
pushed profile if the LAN IP changed. *Expect:* no device touch; v1 devices (if any remain)
need the old IP, so plan the move after v1 retires.

**F8. Lost device (with W5(b)).** Revoke it in the admin. Its sessions die at the next request,
on either address. *Expect:* the device sits on its login or enrollment screen. Its copy of the
service token still works at Cloudflare; rotate the token if the device is not recovered.

---

## 6. Questions

| Ref | Question | Recommendation |
|---|---|---|
| Q6a | Device hostname: Access service token, or open with app auth + rate limit? | Service token, non-expiring, with the LAN fallback as the safety net. |
| Q6b | Admin hostname protection | Cloudflare Access, e-mail one-time PIN, allow-list of your addresses. |
| Q6c | Hostnames | `api.<domain>` and `ops.<domain>` (any two names will do). |
| Q6d | Sync duration | Check the `/shopee/orders` `duration_ms` values in the production logs before stage 2 (§3.3). |
| Q6e | Server LAN IP | DHCP reservation for `192.168.1.50` now. |

Answers (D4): Q6a service token ✅ · Q6b Access + e-mail one-time PIN ✅ · Q6c you configure the
names; this file uses the template `api.<domain>` / `ops.<domain>` ✅ · Q6d sync averages
4–5 s, far below the ~100 s limit ✅ (the sync flow review is pinned as Q25) · Q6e
`192.168.1.50` is outside the DHCP range, effectively static ✅.

---

## 7. Stage 2 runbook (maintainer, later)

Placeholders: `<domain>` = your Cloudflare zone; `api.<domain>` = device API; `ops.<domain>` =
admin. Values marked **VERIFY** must be checked against the Cloudflare dashboard or the pinned
`cloudflared` version when you do this.

**Code prerequisites** (tasks in the v0.6.0 plan or later; stage 2 can't start without them):
- **v2 client:**
  - server profile with primary and fallback addresses plus a service token, editable in hidden
    settings or by enrollment QR;
  - the address-switch rule of §4.2, including an Access block page counting as unreachable;
  - the service-token headers on every request and on the WS upgrade.
- **Backend:**
  - ~~an opt-in `backend/compose.tunnel.yaml` override with the `cloudflared` service~~ done
    (2026-11-23), so stage 1 deployments are unaffected;
  - Uvicorn `--proxy-headers --forwarded-allow-ips=<cloudflared network>`, and the request log
    taking `CF-Connecting-IP`.

### A. Tunnel

1. In Cloudflare: make sure `<domain>` is an active zone (nameservers point at Cloudflare). Open
   **Zero Trust** (the free plan is enough).
2. **Networks → Tunnels → Create a tunnel** → type *Cloudflared*, name `order-checker`. Copy the
   tunnel token into `backend/.secrets/cloudflared_token` (one line), like the other file
   secrets. Do not install a connector on the host: the container below is the connector.
3. The override is in [`backend/compose.tunnel.yaml`](../backend/compose.tunnel.yaml) (image pinned to
   2026.10.7, `--token-file` checked). The image runs as UID 65532 and Compose bind-mounts file
   secrets with their host owner, so give the token file to that UID:
   `sudo chown 65532:65532 .secrets/cloudflared_token && sudo chmod 400 .secrets/cloudflared_token`.
   Deploy with `docker compose -f compose.yaml -f compose.prod.yaml -f compose.tunnel.yaml up -d`.
   The tunnel shows **Healthy** in the dashboard.
4. In the tunnel, under **Public hostnames** (VERIFY the menu name; it is also called *Published
   application routes*):
   - `ops.<domain>` → `http://admin-web:80`
   - `api.<domain>` → `http://server:8000`

   These are compose service names, reached inside the compose network. No host port is
   involved.
5. Don't test yet without Access: both hostnames are now public. Do B and C right away (or
   create the Access apps first, then the hostnames).

### B. Admin hostname: Access with e-mail one-time PIN (Q6b)

1. **Zero Trust → Settings → Authentication → Login methods → Add → One-time PIN.**
2. **Access → Applications → Add → Self-hosted:**
   - Name: *Order Checker admin*. Domain: `ops.<domain>`, all paths. Session duration: 24 h.
   - Policy *Admins*: Action **Allow**, Include **Emails** = your address(es).
3. Test in a private window:
   1. `https://ops.<domain>` → Cloudflare login → PIN by e-mail → the Flutter admin loads.
   2. Log in as admin; live updates arrive. The WS upgrade carries the `CF_Authorization`
      cookie, same origin.
   3. `https://ops.<domain>/console/` once the Vue admin exists.
4. **Expect:** after 24 h, Access asks for a PIN again. The admin app's own login is separate
   and unchanged.

### C. Device hostname: Access service token (Q6a)

1. **Access → Service credentials → Service tokens → Create:** name `order-checker-devices`,
   duration **Non-expiring** (VERIFY it is offered; otherwise the longest available, plus an
   expiry alert). Copy the **Client ID** and **Client Secret** into your password manager. The
   secret is shown only once.
2. **Access → Applications → Add → Self-hosted:**
   - Name: *Order Checker device API*. Domain: `api.<domain>`, all paths.
   - Policy *Devices*: Action **Service Auth** (not *Allow*, which would redirect to a login
     page). Include **Service Token** = `order-checker-devices`.
3. Test from a laptop:
   ```bash
   curl -i https://api.<domain>/meta                                   # blocked by Access (403)
   curl -i https://api.<domain>/meta \
     -H "CF-Access-Client-Id: <id>" -H "CF-Access-Client-Secret: <secret>"   # 200, JSON
   ```
   Then a WebSocket check with the same headers (e.g. `websocat`, with a ticket from
   `POST /auth/ws-token`): leave it idle for 5 minutes. It must stay open, because Uvicorn's
   20 s pings keep it alive (§3.3).

### D. Switch one device (spare first)

1. On the spare device, Wi-Fi **off** (mobile data or a hotspot):
   - set the profile to primary `https://api.<domain>`, fallback `http://192.168.1.50:8000`,
     plus the service token (hidden settings or the enrollment QR);
   - work through a pick, an outbound scan and a stock change; check that live updates arrive.
2. Wi-Fi **on**, then unplug the server's internet uplink (or stop `cloudflared`). The app shows
   the **LAN** chip and keeps working. Restore the uplink; within a few minutes the chip
   disappears.
3. Publish a dummy update (F6) and update the spare device over the domain.
4. Then the two operator devices, one at a time (pilot, Q20).

**The QR carries the service-token secret:** show it on screen, don't print it or keep it.

### E. Rollback and maintenance

- **Rollback:** set the profile back to LAN only (or simply stop `cloudflared`, and the fallback
  takes over). No relogin. The LAN path is never touched by stage 2.
- **Token rotation:**
  1. Create a second service token and add it to the *Devices* policy.
  2. Push the new token to the devices.
  3. Remove the old token from the policy and delete it.
- **Lost device:** revoke it in the admin (W5(b)) and rotate the service token (F8).
- **Optional:** a Cloudflare rate-limiting rule on `api.<domain>/auth/*` as a second layer.
