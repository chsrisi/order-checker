# v2 device day: maintainer checklist (T6.14 MT67 part + T6.16)

Status 2026-11-23: **postponed** (V2_DELTA Delta 5). v0.6.0 is deployed; feature parity
(T6.15, step 7) comes first. This round pilots **one device** (Q20). The second device and
v1 retirement come later.

The release APK allows plain HTTP only to `192.168.1.50`, so the device talks to production.
Use a **test operator account** throughout: "log out everywhere" logs that account out on every
device.

## A. Before the window (your machine) ✅

- [x] Release key generated (V2_SPEC §12.2), backed up, and the restore tested (§12.3)
- [x] SHA-256 fingerprint recorded in RELEASE.md §4
- [x] `frontend/client-android/keystore.properties` (git-ignored) and `oc.settingsPin` in
      `~/.gradle/gradle.properties`
- [x] 2.0.0 (versionCode 1) built; dummy update (versionCode 2) built
- [x] Both APKs checked with `apksigner verify --print-certs`: fingerprint matches RELEASE.md
- [x] Release PR merged, `v0.6.0` tagged
- [x] Test operator account chosen

> If the device day is weeks away, rebuild the APKs from the then-current code before the window.
> Every published versionCode is permanent, so number them from the next unused code.

## B. Deploy v0.6.0 (RELEASE.md §5 "v0.6.0")

- [x] Window announced, backup taken (database, Redis, `data/keys`)
- [x] `backend/data/releases/client` created, v0.6.0 deployed, migrations `d4a7e2c9b1f0` and
      `e5b8f3a1c2d4` in the log, `startup_config_accepted`
- [ ] **Smoke test v1** on both scanners (do this now, independent of the device day): relogin,
      sync, claim, add a pick, delete it (stock comes back), scan a test label
- [ ] **Smoke test from a laptop:**
  - [ ] `curl -s http://192.168.1.50:8000/v2/meta` → `client_contract {"min":1,"max":2}`
  - [ ] `curl -si http://192.168.1.50:8000/v2/items/find?query=x | head -1` → 400 (no
        `X-Client-Version`)
  - [ ] `curl -si http://192.168.1.50:8000/v2/client/latest | head -1` → 404 now, 200 after
        publishing
- [ ] **Publish 2.0.0** (on the device day, or when the pilot APK is final), from `backend/`:
  ```bash
  uv run python -m scripts.publish_client_release <oc-1.apk> --version-code 1 \
    --version-name 2.0.0 --dir data/releases/client            # dry run, check the output
  # then the same command with --confirm
  ```
  `/v2/client/latest` then answers 200 with `version_code` 1.

## C. Pilot device: install, grant, register (T6.14 steps 1–2, T6.16 step 2)

- [ ] Record: `adb shell getprop ro.product.model`, `adb shell getprop ro.build.display.id`,
      Play services present (`adb shell pm list packages com.google.android.gms`)
- [ ] `adb install oc-1.apk` (installs beside v1; v1 stays)
- [ ] Grant "install unknown apps":
      `adb shell appops set com.bakingholic.orderchecker REQUEST_INSTALL_PACKAGES allow`
      (or let the app send you to Settings; on Android 11 the app restarts once)
- [ ] Open the app: the update check runs first; no banner (1 is the latest)
- [ ] Log in with the test operator: "Live updates: connected", "Stock locations: …"
- [ ] `GET /admin/devices`: the device is `pending`, with model, Android version and
      `app_version_code: 1`
- [ ] Hidden settings: hold the version label 5 s, enter the PIN; profile shows
      `http://192.168.1.50:8000` and the device id

## D. OTA on the device (T6.14 steps 3–5, T6.16 step 3)

- [ ] **Optional update:** publish `oc-2.apk` as `--version-code 2`. Reopen the app → banner →
      Update → Install. The label shows `v2.0.1 (2)`; `/admin/devices` shows
      `app_version_code: 2`
- [ ] **Play Protect:** note whether "App scan recommended" appears, and on which updates.
      Choose More details → **Install without scanning**. Never "Scan app" (it uploads the APK)
- [ ] **Required update:** build 3, publish with `--min-supported 3`; the blocking "Update
      required" screen appears; update
- [ ] **Logged out:** log out, publish 4, update from the login screen
- [ ] *Optional negative check:* publish 5, change one character of `sha256` in `latest.json` →
      "damaged (SHA-256 mismatch)", app stays on 4. Then publish a correct 6

## E. Scanner and session checks (T6.14 step 6)

- [ ] **Wedge suffix:** hidden settings → **Scanner** → scan a barcode into "Scan a test barcode".
      It shows the value, its length and the key that ended it (Enter or Tab); a warning means the
      Suffix setting differs. Set it to match. If nothing appears, the scanner sends no suffix:
      configure Enter in the scanner settings. Also note whether the soft keyboard pops up.
- [ ] **Revocation, v2:** admin → "log out everywhere" on the test operator → v2 returns to login
      with "Session ended" within seconds
- [ ] **Revocation, v1** (open since T6.2): log the test operator into v1 on the pilot device,
      "log out everywhere" → v1 shows its login screen on its next request

## F. Wrap up

- [ ] Leave the pilot device on the newest build; operators keep v1 for real work until parity
      ships
- [ ] Send the results to the agent for the §7 tracker (T6.14, T6.16):
  - model and Android build
  - Play Protect yes/no and how often
  - wedge suffix
  - any failed step, with a screenshot
- [ ] **If it goes badly:** `adb uninstall com.bakingholic.orderchecker` (v1 is unaffected).
      Backend rollback: RELEASE.md §5 "v0.6.0"
