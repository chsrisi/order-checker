package com.bakingholic.orderchecker.updater

import com.bakingholic.orderchecker.api.model.ClientReleaseResponse
import com.bakingholic.orderchecker.core.AppInfo
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Everything the UI shows about updates. */
sealed interface UpdateState {
    data object Idle : UpdateState

    data object Checking : UpdateState

    data object UpToDate : UpdateState

    data class Unreachable(val error: String?) : UpdateState

    data class Available(val release: ClientReleaseResponse, val required: Boolean, val address: String) : UpdateState

    data class Downloading(val release: ClientReleaseResponse, val required: Boolean, val progress: Float) : UpdateState

    data class Installing(val release: ClientReleaseResponse, val required: Boolean) : UpdateState

    data class Failed(val release: ClientReleaseResponse?, val required: Boolean, val reason: String) : UpdateState
}

/** Hands a verified APK to the system installer (Android: PackageInstaller session). */
interface ApkInstaller {
    /** Ask whether this app may install packages; false → the UI explains and opens Settings. */
    fun canInstall(): Boolean

    fun openInstallPermissionSettings()

    /** Starts the install; the outcome arrives through [UpdateManager.installFinished]. */
    fun install(apk: File)
}

/**
 * Check → download → verify → install (T6.12). One operation at a time; the state survives
 * screen changes. A required update stays required until the app is replaced.
 */
class UpdateManager(
    private val appInfo: AppInfo,
    private val checker: UpdateChecker,
    private val verifier: ApkVerifier,
    private val installer: ApkInstaller,
    private val downloadDir: File,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state: StateFlow<UpdateState> = _state
    private val lock = Mutex()
    private var lastCheck = 0L
    private var postponed: Int? = null

    /**
     * Deletes leftover downloads. A successful install replaces the process before
     * [installFinished] can run, so the next start cleans up.
     */
    fun clearDownloads() {
        downloadDir.listFiles()?.forEach { it.delete() }
    }

    /** Checks unless one ran within [minIntervalMillis]. Returns the decision. */
    suspend fun check(minIntervalMillis: Long = 0): UpdateDecision? = lock.withLock {
        if (_state.value is UpdateState.Downloading || _state.value is UpdateState.Installing) return null
        if (minIntervalMillis > 0 && clock() - lastCheck < minIntervalMillis) return null
        lastCheck = clock()
        _state.value = UpdateState.Checking
        when (val result = checker.latest()) {
            is CheckResult.Unreachable -> {
                _state.value = UpdateState.Unreachable(result.error)
                null
            }
            is CheckResult.Answered -> {
                val decision = UpdatePolicy.decide(appInfo.versionCode, result.release)
                _state.value = when (decision) {
                    UpdateDecision.UpToDate -> UpdateState.UpToDate
                    is UpdateDecision.Optional ->
                        if (postponed == decision.release.versionCode) {
                            UpdateState.UpToDate
                        } else {
                            UpdateState.Available(decision.release, false, result.address)
                        }
                    is UpdateDecision.Required -> UpdateState.Available(decision.release, true, result.address)
                }
                decision
            }
        }
    }

    /** "Later" on an optional update: hide it until a newer one is published. */
    fun postpone() {
        val current = _state.value as? UpdateState.Available ?: return
        if (current.required) return
        postponed = current.release.versionCode
        _state.value = UpdateState.UpToDate
    }

    /** Download, verify and install the available release. */
    suspend fun update() {
        val available = _state.value as? UpdateState.Available
            ?: (_state.value as? UpdateState.Failed)?.let { failed ->
                failed.release?.let { check(); _state.value as? UpdateState.Available }
            }
            ?: return
        if (!installer.canInstall()) {
            _state.value = UpdateState.Failed(available.release, available.required, PERMISSION_MESSAGE)
            installer.openInstallPermissionSettings()
            return
        }
        val release = available.release
        val target = File(downloadDir, "orderchecker-${release.versionCode}.apk")
        try {
            _state.value = UpdateState.Downloading(release, available.required, 0f)
            checker.download(available.address, release, target) { progress ->
                _state.value = UpdateState.Downloading(release, available.required, progress)
            }
            verifier.verify(target, release.sha256)?.let { reason ->
                target.delete()
                _state.value = UpdateState.Failed(release, available.required, reason.message)
                return
            }
            _state.value = UpdateState.Installing(release, available.required)
            installer.install(target)
        } catch (e: Exception) {
            target.delete()
            _state.value = UpdateState.Failed(release, available.required, "Download failed: ${e.message}")
        }
    }

    /** Called by the installer's result receiver. Success replaces the process. */
    fun installFinished(success: Boolean, message: String?) {
        val current = _state.value
        val release = (current as? UpdateState.Installing)?.release
        val required = (current as? UpdateState.Installing)?.required ?: false
        downloadDir.listFiles()?.forEach { it.delete() }
        _state.value = if (success) {
            UpdateState.UpToDate
        } else {
            UpdateState.Failed(release, required, message ?: "Installation cancelled or failed.")
        }
    }

    companion object {
        const val PERMISSION_MESSAGE = "Allow \"Install unknown apps\" for Order Checker, then tap Update again."
    }
}
