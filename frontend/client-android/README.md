# Order Checker operator app v2 (Android)

Kotlin + Jetpack Compose app for the warehouse scanners (Newland MT67, Android 11). It speaks
operator-client **contract v2** (`/v2`, see `docs/API.md`) and updates itself over the air
from the backend. The v1 Flutter app (`frontend/client`) stays in the field until v2 replaces
it.

## Build

Requirements: JDK 17+ (Android Studio's `jbr` works) and the Android SDK with platform
`android-37.2` and build-tools 37.

```bash
./gradlew lint testDebugUnitTest assembleDebug          # debug: com.bakingholic.orderchecker.debug
./gradlew assembleRelease                                # signed release (needs the key, below)
./gradlew assembleRelease -Poc.unsignedRelease=true      # unsigned, as CI builds it
```

Debug builds use the `.debug` application id and a `-debug` version suffix, so they install
next to the release app and can never update it. Debug builds also allow plain HTTP to the
emulator host `10.0.2.2`; release builds allow plain HTTP only to `192.168.1.50`.

### Emulator rehearsal build

`assembleRehearsal` is the release build (R8, release signing, production application id)
that also allows plain HTTP to the emulator host `10.0.2.2`. It exists only to rehearse OTA on
the emulator against a local backend (IMPLEMENTATION_PLAN T6.14); never publish it to devices.
Sign it with a throwaway key through the `OC_*` variables, never with the production key.

## Versions

`gradle.properties`: `oc.versionCode` (integer, sent as `X-Client-Version`) and
`oc.versionName`. Raise `oc.versionCode` by 1 for every APK you publish and never reuse one:
the backend refuses a lower or equal code, and Android refuses downgrades.

## Release signing

The key is generated and kept by the maintainer (`docs/V2_SPEC.md` §12). Create
`keystore.properties` in this directory (git-ignored):

```properties
storeFile=/home/<you>/keys/orderchecker/orderchecker-release.p12
storePassword=<password>
keyAlias=orderchecker
keyPassword=<same password>
```

or set `OC_KEYSTORE_PATH`, `OC_KEYSTORE_PASSWORD`, `OC_KEY_ALIAS`, `OC_KEY_PASSWORD`. Without
either, `assembleRelease` fails on purpose. Verify before publishing:

```bash
$ANDROID_HOME/build-tools/37.0.0/apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk
```

Then publish it with the backend script (`docs/OPERATIONS.md` "Publishing a client release").

## Server profile and hidden settings

The app talks to the backend through a **server profile**: `primary`, optional `fallback`,
optional Cloudflare Access service token (`docs/V2_SERVER_ADDRESS.md` §4.2). The build default
is the stage-1 LAN server `http://192.168.1.50:8000`; override it per build with
`-Poc.defaultServer=...` (for example `http://10.0.2.2:8000` for the emulator and a local
backend). A connection failure (DNS, TCP, TLS, timeout, Cloudflare 52x, Access block page)
moves to the other address; any HTTP answer, even 4xx, does not. On the fallback, a "LAN" chip
shows and the primary is probed every 3 minutes.

**Hidden settings:** hold the version label at the bottom for 5 seconds, then enter the PIN.
The PIN is build configuration and never committed: put `oc.settingsPin=<digits>` in
`~/.gradle/gradle.properties`, pass `-Poc.settingsPin=...`, or set `OC_SETTINGS_PIN`. A build
without a PIN cannot open the settings. There you can edit the profile (no relogin needed), and
see the app version and the device registration.

## Sessions and live updates

- Every request carries `X-Client-Version: <versionCode>`. A 426 (or WS close 4426) shows the
  update screen.
- Tokens are encrypted with an Android Keystore AES-GCM key and kept in DataStore; backups and
  device transfers exclude them. The app reads only `sub`, `sid` and `exp` from its token (no
  local verification), and refreshes a minute before expiry.
- A 401 triggers one refresh, shared by all requests in flight, and one retry; if the refresh
  is rejected the app logs out (this is how "log out everywhere" reaches a device).
- `/v2/ws` reconnects forever with backoff (1 s doubling to 30 s, ±20 %) and at once when the
  network comes back. Close 4401 or 1008 → one fresh ticket, then a session check.

## Over-the-air updates

The updater (`updater/`) does not depend on the login state. It checks `GET
/v2/client/latest` on **every** address of the profile:

- at app start, before the login screen;
- on resume (at most once a minute);
- every 15 minutes in the background (WorkManager);
- on "Check for update now" in the hidden settings.

A release below `min_supported_version_code` (or any 426) shows a blocking "Update required"
screen. A newer optional release shows a banner with **Update** / **Later**. Before
installing, the app checks the SHA-256 against `latest.json`, and that the package name and
signing certificate match the installed app and the versionCode is higher. Then it installs
through a PackageInstaller session.

What an operator sees on Android 11 (checked on the API 30 emulator):

1. The first update asks for **Install unknown apps** for Order Checker. Android restarts the
   app after it is granted; tap **Update** again.
2. The Android prompt "Do you want to install an update…?" → **Install** (every update, one
   tap; Android 11 cannot skip it).
3. On devices with Google Play Protect, **every** update may show "App scan recommended"
   (Play Protect has not seen the new APK): **More details → Install without scanning** (do
   not send the app to Google). The MT67 may not have Play services; check on the device day.
4. The app closes; reopen it and the version label shows the new build.

## Device identity

On first use the app creates an EC P-256 key pair in the Android Keystore (`oc_device`,
non-exportable, signing only). After every login it calls `POST /v2/device/register` with the
public key, model, Android version and versionCode, signing the access token's `sid`. New
devices are `pending` in `GET /admin/devices`; approval and revocation screens come with step
8. Registration retries with backoff when offline (it is idempotent on the server), and the
hidden settings show the device id and status. Uninstalling the app (or clearing its data)
deletes the key: the device then registers as a new `pending` device.

## Layout

- `core/`: app identity (`AppInfo`: versionCode, contract).
- `net/`: server profile, address switching, HTTP client.
- `auth/`: tokens (encrypted store, claims), `SessionManager` (login, refresh, logout).
- `ws/`: `/v2/ws` client, frame parser, backoff, close-code rules.
- `settings/`: profile store, PIN gate. `meta/`: `/v2/meta`. `ui/`: Compose screens.
- `api/model/` (generated, `build/generated/openapi`): models from `backend/openapi/v2.json`.
  Regenerated on every build; never edit or commit them.
- `updater/`: update policy, APK verification, download, PackageInstaller, periodic worker.
- `device/`: Keystore device key, registration with retry.
- `scan/` + `ui/scan/`: the wedge scan input (T6.15a): `ScanField`, suffix setting, scanner test.

## Scanning (keyboard wedge)

Every scanning screen uses `ui/scan/ScanField`. While scanning, the field is **read-only**: it
opens no input session, so the soft keyboard stays closed, and the characters are taken from the
key events. The configured suffix (Enter by default, or Tab) submits; the field clears itself and
keeps focus. The same value twice within 300 ms (a double fire) is dropped. To type by hand, tap
the field or press **Type**; the keyboard opens and closes again after the submit.

The suffix is set per device in the hidden settings → **Scanner**. The scanner test there
accepts both suffixes and shows each value, its length and the key that ended it, and warns
when the scanner sends a different suffix from the setting.
