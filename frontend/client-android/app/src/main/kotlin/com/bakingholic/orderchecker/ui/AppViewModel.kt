package com.bakingholic.orderchecker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bakingholic.orderchecker.AppGraph
import com.bakingholic.orderchecker.auth.LoginRequestResult
import com.bakingholic.orderchecker.auth.LoginWait
import com.bakingholic.orderchecker.device.DeviceState
import com.bakingholic.orderchecker.device.DeviceStatus
import com.bakingholic.orderchecker.net.ApiException
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.net.ServerUnreachableException
import com.bakingholic.orderchecker.net.UpgradeRequiredException
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.ops.OpsController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val DEVICE_REVOKED = "This device was revoked by the admin."

sealed interface Screen {
    data object Starting : Screen

    data class Login(
        val busy: Boolean = false,
        val error: String? = null,
        val waiting: LoginWait? = null,
        /** A line under the error, not an error itself (the logout reason, W8). */
        val notice: String? = null,
        /** The admin chose this worker: open the password step for them (T8.7). */
        val preselect: String? = null,
    ) : Screen

    data object Home : Screen

    data class UpdateRequired(val minSupportedVersionCode: Int?) : Screen
}

/** The login screen polls for a worker switch only while idle and in the foreground (W5). */
fun pollsDeviceState(screen: Screen, foreground: Boolean): Boolean =
    foreground && screen is Screen.Login && !screen.busy && screen.waiting == null

/** The login screen after a state poll that did not log in (T8.7). */
fun loginAfter(login: Screen.Login, state: DeviceState): Screen.Login = when (state) {
    is DeviceState.Preselect -> login.copy(
        error = null, // "Session ended" is answered by the admin's choice
        preselect = state.username,
        notice = listOfNotNull(state.logoutReason, "The admin chose ${state.username}. Enter the password.").joinToString(" "),
    )
    is DeviceState.Idle -> login.copy(notice = state.logoutReason)
    DeviceState.Revoked -> login.copy(error = DEVICE_REVOKED, notice = null)
    DeviceState.ClockOff -> login.copy(notice = "The device clock is wrong: the admin can't switch workers on it.")
    is DeviceState.LoggedIn -> login
}

class AppViewModel(val graph: AppGraph) : ViewModel() {
    private val _screen = MutableStateFlow<Screen>(Screen.Starting)
    val screen: StateFlow<Screen> = _screen
    private val _settingsOpen = MutableStateFlow(false)
    val settingsOpen: StateFlow<Boolean> = _settingsOpen
    private val _onFallback = MutableStateFlow(false)
    val onFallback: StateFlow<Boolean> = _onFallback

    val user = graph.session.user
    val wsState = graph.ws.state
    val meta = graph.meta.meta
    val updateState = graph.updates.state
    val deviceStatus = graph.device.status
    val scanSuffix: StateFlow<ScanSuffix> =
        graph.scanPrefs.suffix.stateIn(viewModelScope, SharingStarted.Eagerly, ScanSuffix.ENTER)
    val knownWorkers: StateFlow<List<String>> =
        graph.knownWorkers.names.stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())
    private val foreground = MutableStateFlow(false)
    private val _homeNotice = MutableStateFlow<String?>(null)

    /** Shown once on the home screen ("Logged in by the admin as …"). */
    val homeNotice: StateFlow<String?> = _homeNotice
    private var registration: Job? = null
    private var loginRequest: Job? = null
    val ops = OpsController(graph.ops, viewModelScope)

    init {
        viewModelScope.launch {
            graph.events.collect { event ->
                when (event) {
                    is AppEvent.LoggedOut -> {
                        ops.selectOrder(null)
                        // A socket close or 401 can arrive after the revoked registration.
                        _screen.value = Screen.Login(
                            error = if (graph.device.status.value == DeviceStatus.Revoked) {
                                DEVICE_REVOKED
                            } else {
                                "Session ended. Please log in again."
                            },
                        )
                    }
                    is AppEvent.DeviceRevoked -> {
                        ops.selectOrder(null)
                        _screen.value = Screen.Login(error = DEVICE_REVOKED)
                    }
                    is AppEvent.UpgradeRequired -> {
                        _screen.value = Screen.UpdateRequired(event.minSupportedVersionCode)
                        viewModelScope.launch { graph.updates.check() }
                    }
                }
            }
        }
        viewModelScope.launch {
            // The update check comes first, before the login screen (T6.12): a build with a
            // broken login must still be replaceable.
            graph.updates.check()
            _screen.value = if (graph.session.restore()) Screen.Home.also { enterHome() } else Screen.Login()
        }
        viewModelScope.launch {
            combine(_screen, foreground, ::pollsDeviceState).distinctUntilChanged().collectLatest { polling ->
                if (polling) graph.deviceState.run(::onDeviceState)
            }
        }
        viewModelScope.launch {
            while (isActive) {
                graph.api.probePrimaryIfDue()
                _onFallback.value = graph.selector.onFallback()
                delay(5_000)
            }
        }
    }

    fun setForeground(value: Boolean) {
        foreground.value = value
    }

    fun homeNoticeShown() {
        _homeNotice.value = null
    }

    /** One answer of the state poll; false stops polling until the login screen changes. */
    private fun onDeviceState(state: DeviceState): Boolean {
        val login = _screen.value as? Screen.Login ?: return false
        if (state is DeviceState.LoggedIn) {
            _homeNotice.value = "Logged in by the admin as ${state.username}."
            enterHome()
            _screen.value = Screen.Home
            return false
        }
        _screen.value = loginAfter(login, state)
        return state !is DeviceState.Revoked && state != DeviceState.ClockOff
    }

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isEmpty()) return
        _screen.value = Screen.Login(busy = true)
        viewModelScope.launch {
            _screen.value = try {
                graph.session.login(username.trim(), password)
                enterHome()
                Screen.Home
            } catch (e: UpgradeRequiredException) {
                Screen.UpdateRequired(e.minSupportedVersionCode)
            } catch (e: ApiException) {
                Screen.Login(error = loginError(e))
            } catch (e: ServerUnreachableException) {
                Screen.Login(error = "Server unreachable. Check the Wi-Fi.")
            } catch (e: Exception) {
                Screen.Login(error = "Login failed: ${e.message}")
            }
        }
    }

    /** Asks an admin to approve [username]'s login (T6.23). */
    fun requestLogin(username: String) {
        _screen.value = Screen.Login(busy = true)
        loginRequest?.cancel()
        loginRequest = viewModelScope.launch {
            _screen.value = try {
                when (graph.loginRequests.request(username) { _screen.value = Screen.Login(waiting = it) }) {
                    LoginRequestResult.APPROVED -> Screen.Home.also { enterHome() }
                    LoginRequestResult.DENIED -> Screen.Login(error = "The admin denied the login.")
                    LoginRequestResult.EXPIRED -> Screen.Login(error = "No admin answered in time.")
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: UpgradeRequiredException) {
                Screen.UpdateRequired(e.minSupportedVersionCode)
            } catch (e: ApiException) {
                Screen.Login(error = requestError(e))
            } catch (e: ServerUnreachableException) {
                Screen.Login(error = "Server unreachable. Check the Wi-Fi.")
            } catch (e: Exception) {
                Screen.Login(error = "Request failed: ${e.message}")
            }
        }
    }

    fun cancelLoginRequest() {
        loginRequest?.cancel()
        if (_screen.value is Screen.Login) _screen.value = Screen.Login()
    }

    fun clearLoginError() {
        val login = _screen.value as? Screen.Login ?: return
        if (login.error != null) _screen.value = login.copy(error = null)
    }

    fun logout() {
        registration?.cancel()
        ops.selectOrder(null)
        viewModelScope.launch {
            graph.session.logout()
            _screen.value = Screen.Login()
        }
    }

    fun checkForUpdate(minIntervalMillis: Long = 0) {
        viewModelScope.launch { graph.updates.check(minIntervalMillis) }
    }

    fun installUpdate() {
        viewModelScope.launch { graph.updates.update() }
    }

    fun postponeUpdate() = graph.updates.postpone()

    fun openSettings() {
        _settingsOpen.value = true
    }

    fun closeSettings() {
        _settingsOpen.value = false
    }

    fun forgetWorker(username: String) {
        viewModelScope.launch { graph.knownWorkers.forget(username) }
    }

    fun forgetAllWorkers() {
        viewModelScope.launch { graph.knownWorkers.forgetAll() }
    }

    fun setScanSuffix(suffix: ScanSuffix) {
        viewModelScope.launch { graph.scanPrefs.setSuffix(suffix) }
    }

    fun saveProfile(profile: ServerProfile, onResult: (String?) -> Unit) {
        viewModelScope.launch {
            onResult(runCatching { graph.profileStore.save(profile) }.exceptionOrNull()?.message)
        }
    }

    private fun enterHome() {
        graph.ws.start()
        registration?.cancel()
        registration = viewModelScope.launch { graph.device.registerWithRetry() }
        viewModelScope.launch { runCatching { graph.meta.refresh() } }
    }

    private fun requestError(e: ApiException): String = when {
        e.code == 403 && e.detail == "Device revoked" -> DEVICE_REVOKED
        e.code == 403 -> "This device is not registered yet. Log in with a password once."
        e.code == 429 -> "Too many requests. Wait a few minutes."
        e.code == 503 -> "Requests are not available right now. Use the password."
        else -> e.detail ?: "Request failed (${e.code})."
    }

    private fun loginError(e: ApiException): String = when (e.code) {
        401 -> "Wrong username or password."
        429 -> "Too many attempts. Wait 15 minutes."
        403 -> "This account cannot use the scanner app."
        else -> e.detail ?: "Login failed (${e.code})."
    }
}
