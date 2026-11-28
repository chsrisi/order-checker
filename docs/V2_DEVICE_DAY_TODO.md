# v2 device day: maintainer checklist (T6.14 MT67 part + T6.16)

Status 2026-11-23: **postponed** (V2_DELTA Delta 5). v0.6.0 is deployed; feature parity
(T6.15, step 7) comes first. This round pilots **one device** (Q20). The second device and
v1 retirement come later.

**Device day 1: 2026-11-28**, on v0.7.0. Everything done except recording the device facts
(model, build), which follow on day 2. **Both scanners now run v2, build 3 (2.1.0)**, tested and
used in operation; v1 is sunset after one observed operating week (V2_DELTA Delta 15). Findings and fixes: "Device day 1 findings" below.

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
> **Required since T6.18 (2026-11-25):** APKs built before it call pick endpoints the backend no
> longer has. Build 2.0.0 and the dummy update again, against a backend that includes T6.18.
> Every published versionCode is permanent, so number them from the next unused code.

## B. Deploy v0.6.0 (RELEASE.md §5 "v0.6.0")

- [x] Window announced, backup taken (database, Redis, `data/keys`)
- [x] `backend/data/releases/client` created, v0.6.0 deployed, migrations `d4a7e2c9b1f0` and
      `e5b8f3a1c2d4` in the log, `startup_config_accepted`
- [x] **Smoke test v1** on both scanners (done 2026-11-27, all good): relogin,
      sync, claim, add a pick, delete it (stock comes back), scan a test label
- [x] **Smoke test from a laptop:**
  - [x] `curl -s http://192.168.1.50:8000/v2/meta` → `client_contract {"min":1,"max":2}`
  - [x] `curl -si http://192.168.1.50:8000/v2/items/find?query=x | head -1` → 400 (no
        `X-Client-Version`)
  - [x] `curl -si http://192.168.1.50:8000/v2/client/latest | head -1` → 404 now, 200 after
        publishing
- [x] **Publish 2.0.0** (on the device day, or when the pilot APK is final), from `backend/`:

  ```bash
  uv run python -m scripts.publish_client_release <oc-1.apk> --version-code 1 \
    --version-name 2.0.0 --dir data/releases/client            # dry run, check the output
  # then the same command with --confirm
  ```

  `/v2/client/latest` then answers 200 with `version_code` 1.

## C. Pilot device: install, grant, register (T6.14 steps 1–2, T6.16 step 2)

- [ ] Record: `adb shell getprop ro.product.model`, `adb shell getprop ro.build.display.id`,
      Play services present (`adb shell pm list packages com.google.android.gms`): **Play
      services present** (day 1); model and build on day 2. Also record the screen:
      `adb shell wm size` and `adb shell wm density` (see the findings below)
- [x] `adb install oc-1.apk` (installs beside v1; v1 stays)
- [x] Grant "install unknown apps":
      `adb shell appops set com.bakingholic.orderchecker REQUEST_INSTALL_PACKAGES allow`
      (or let the app send you to Settings; on Android 11 the app restarts once)
- [x] Open the app: the update check runs first; no banner (1 is the latest)
- [x] Log in with the test operator: "Live updates: connected", "Stock locations: …"
- [x] `GET /admin/devices`: the device is `pending`, with model, Android version and
      `app_version_code: 1`
- [x] Hidden settings: hold the version label 5 s, enter the PIN; profile shows
      `http://192.168.1.50:8000` and the device id

## D. OTA on the device (T6.14 steps 3–5, T6.16 step 3)

- [x] **Optional update:** publish `oc-2.apk` as `--version-code 2`. Reopen the app → banner →
      Update → Install. The label shows `v2.0.1 (2)`; `/admin/devices` shows
      `app_version_code: 2`
- [x] **Play Protect:** note whether "App scan recommended" appears, and on which updates.
      Choose More details → **Install without scanning**. Never "Scan app" (it uploads the APK).
      **Result (day 1): it pops up on every install**, as on the emulator (T6.14)
- [x] **Required update:** build 3, publish with `--min-supported 3`; the blocking "Update
      required" screen appears; update
- [x] **Logged out:** log out, publish 4, update from the login screen
- [x] *Optional negative check:* publish 5, change one character of `sha256` in `latest.json` →
      "damaged (SHA-256 mismatch)", app stays on 4. Then publish a correct 6

## E. Scanner and session checks (T6.14 step 6)

- [x] **Wedge suffix:** hidden settings → **Scanner** → scan a barcode into "Scan a test barcode".
      It shows the value, its length and the key that ended it (Enter or Tab); a warning means the
      Suffix setting differs. Set it to match. If nothing appears, the scanner sends no suffix:
      configure Enter in the scanner settings. Also note whether the soft keyboard pops up.
- [x] **Revocation, v2:** admin → "log out everywhere" on the test operator → v2 returns to login
      with "Session ended" within seconds
- [x] **Revocation, v1** (open since T6.2): log the test operator into v1 on the pilot device,
      "log out everywhere" → v1 shows its login screen on its next request

## F. Wrap up

- [ ] **Operators' feedback** (pinned, V2_DELTA Delta 12): Picking and Outbound (T6.20), and
      login requests (L1–L9: the 2-minute wait, the 2-digit code, the console badge). Note what
      they trip over
- [ ] Leave the pilot device on the newest build; operators keep v1 for real work until parity
      ships
- [ ] Send the results to the agent for the §7 tracker (T6.14, T6.16):
  - model and Android build
  - Play Protect yes/no and how often
  - wedge suffix
  - any failed step, with a screenshot
- [ ] **If it goes badly:** `adb uninstall com.bakingholic.orderchecker` (v1 is unaffected).
      Backend rollback: RELEASE.md §5 "v0.6.0"

## Device day 1 findings (2026-11-28)

| # | Finding | Cause | Fix (branch `fix/android-device-day-1`) |
|---|---|---|---|
| 1 | Outbound: the field loses focus after a scan (Enter) | The field was disabled while saving, so the focus moved to the top bar's back arrow; the next scan's Enter pressed it, went Home and **lost that scan** | The scan field stays focused while saving and refuses a scan in that moment with "Still saving. Scan … again." The top bar and the task menu never take key focus. Same for Finder and Stockkeeping, which also disabled the field |
| 2 | Count (Stockkeeping and count tasks): the last shelf stays after going back | Back to the shelf scan cleared the item but kept the location (the path line still showed it) | Back to the shelf scan forgets the shelf, the item and the quantity |
| 3 | The real screen is shorter than the Small_Phone emulator: Finder is cut to ½–¾ | Five fixed 72 dp buttons; the menu did not scroll | Home buttons share the height (72 dp down to 48 dp) and the menu scrolls below that. Baseline AVD: 480×854 at 240 dpi with the 3-button bar (`hw.mainKeys=no`), which reproduces the cut Finder. Confirm with the real `wm size` / `wm density` on day 2 |
| 4 | Back arrow and the "more" button too small | They were text glyphs ("←", "⋯") | Vector drawables (Material `arrow_back`, `more_vert`) in 48 dp icon buttons |
| – | Outbound: the newest scan was half hidden above the list on a short screen | The list kept the previous row in place when a new scan arrived on top | The list returns to the top on each new scan |
