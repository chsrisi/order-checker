package com.bakingholic.orderchecker

import android.content.Context
import android.os.Build
import com.bakingholic.orderchecker.device.DataStoreRegistrationStore
import com.bakingholic.orderchecker.device.DeviceRegistrar
import com.bakingholic.orderchecker.device.KeystoreDeviceKeys
import android.net.ConnectivityManager
import android.net.Network
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStore
import com.bakingholic.orderchecker.auth.AesGcmBox
import com.bakingholic.orderchecker.auth.EncryptedTokenStore
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.meta.MetaRepository
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.settings.PinGate
import com.bakingholic.orderchecker.settings.ProfileStore
import com.bakingholic.orderchecker.updater.AndroidPackageInspector
import com.bakingholic.orderchecker.updater.ApkVerifier
import com.bakingholic.orderchecker.updater.PackageInstallerApkInstaller
import com.bakingholic.orderchecker.updater.UpdateChecker
import com.bakingholic.orderchecker.updater.UpdateManager
import com.bakingholic.orderchecker.ws.WsClient
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient

private val Context.settingsStore: DataStore<Preferences> by preferencesDataStore("settings")
private val Context.secureStore: DataStore<Preferences> by preferencesDataStore("secure")

/** Hand-wired app dependencies (one per process). */
class AppGraph(context: Context) {
    val appInfo = AppInfo(BuildConfig.VERSION_CODE, BuildConfig.VERSION_NAME)
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _events = MutableSharedFlow<AppEvent>(extraBufferCapacity = 16)
    val events: SharedFlow<AppEvent> = _events
    private val emit: (AppEvent) -> Unit = { _events.tryEmit(it) }

    val defaultProfile = ServerProfile(primary = BuildConfig.DEFAULT_SERVER)
    val profileStore = ProfileStore(context.settingsStore, defaultProfile)

    @Volatile
    var profile: ServerProfile = runBlocking { profileStore.profile.first() }
        private set

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    val selector = AddressSelector()
    val api = ApiClient(http, appInfo, { profile }, selector, emit)
    val session = SessionManager(
        api,
        EncryptedTokenStore(context.secureStore, AesGcmBox(AesGcmBox.keystoreKey("oc_tokens"))),
        onEvent = emit,
        onLocalLogout = { clearCaches() },
    )
    val meta = MetaRepository(api)
    val ws = WsClient(http, session, appInfo, { profile }, { selector.order().firstOrNull() }, emit, scope)
    val pinGate = PinGate(BuildConfig.SETTINGS_PIN)

    // Device identity (T6.13): Keystore key, registered after every login.
    val device = DeviceRegistrar(
        session,
        KeystoreDeviceKeys(),
        appInfo,
        model = "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
        androidVersion = Build.VERSION.RELEASE,
        store = DataStoreRegistrationStore(context.settingsStore),
    )

    // OTA updater (T6.12): independent of the login state.
    val updates = UpdateManager(
        appInfo,
        UpdateChecker(http, appInfo, { profile }),
        ApkVerifier(AndroidPackageInspector(context)),
        PackageInstallerApkInstaller(context),
        downloadDir = File(context.cacheDir, "updates"),
    )

    init {
        scope.launch { profileStore.profile.collect { profile = it } }
        scope.launch { updates.clearDownloads() }
        context.getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = ws.kick()
            },
        )
    }

    /** Orders, picks and other per-operator caches are dropped on logout (filled by later tasks). */
    private fun clearCaches() {
        ws.stop()
    }
}
