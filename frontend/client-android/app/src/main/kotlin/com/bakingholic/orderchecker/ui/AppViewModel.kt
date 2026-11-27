package com.bakingholic.orderchecker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bakingholic.orderchecker.AppGraph
import com.bakingholic.orderchecker.auth.LoginRequestResult
import com.bakingholic.orderchecker.auth.LoginWait
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
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Starting : Screen

    data class Login(val busy: Boolean = false, val error: String? = null, val waiting: LoginWait? = null) : Screen

    data object Home : Screen

    data class UpdateRequired(val minSupportedVersionCode: Int?) : Screen
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
    private var registration: Job? = null
    private var loginRequest: Job? = null
    val ops = OpsController(
        graph.ops,
        viewModelScope,
        graph.meta.meta.map { it?.stockLocationMode }.stateIn(viewModelScope, SharingStarted.Eagerly, null),
    )

    init {
        viewModelScope.launch {
            graph.events.collect { event ->
                when (event) {
                    is AppEvent.LoggedOut -> {
                        ops.selectOrder(null)
                        _screen.value = Screen.Login(error = "Session ended. Please log in again.")
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
            while (isActive) {
                graph.api.probePrimaryIfDue()
                _onFallback.value = graph.selector.onFallback()
                delay(5_000)
            }
        }
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
        e.code == 403 && e.detail == "Device revoked" -> "This device was revoked by the admin."
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
