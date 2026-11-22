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

## Layout

- `core/`: app identity (`AppInfo`: versionCode, contract).
- `api/model/` (generated, `build/generated/openapi`): models from `backend/openapi/v2.json`.
  Regenerated on every build; never edit or commit them.
- Feature packages (network, auth, updater, device, ...) are added by IMPLEMENTATION_PLAN
  T6.11–T6.13.
