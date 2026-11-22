package com.bakingholic.orderchecker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bakingholic.orderchecker.AppGraph
import com.bakingholic.orderchecker.net.ApiException
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.net.ServerUnreachableException
import com.bakingholic.orderchecker.net.UpgradeRequiredException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Starting : Screen

    data class Login(val busy: Boolean = false, val error: String? = null) : Screen

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

    init {
        viewModelScope.launch {
            graph.events.collect { event ->
                when (event) {
                    is AppEvent.LoggedOut -> _screen.value = Screen.Login(error = "Session ended. Please log in again.")
                    is AppEvent.UpgradeRequired -> _screen.value = Screen.UpdateRequired(event.minSupportedVersionCode)
                }
            }
        }
        viewModelScope.launch {
            // The updater (T6.12) runs before this; then restore the session.
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

    fun logout() {
        viewModelScope.launch {
            graph.session.logout()
            _screen.value = Screen.Login()
        }
    }

    fun openSettings() {
        _settingsOpen.value = true
    }

    fun closeSettings() {
        _settingsOpen.value = false
    }

    fun saveProfile(profile: ServerProfile, onResult: (String?) -> Unit) {
        viewModelScope.launch {
            onResult(runCatching { graph.profileStore.save(profile) }.exceptionOrNull()?.message)
        }
    }

    private fun enterHome() {
        graph.ws.start()
        viewModelScope.launch { runCatching { graph.meta.refresh() } }
    }

    private fun loginError(e: ApiException): String = when (e.code) {
        401 -> "Wrong username or password."
        429 -> "Too many attempts. Wait 15 minutes."
        403 -> "This account cannot use the scanner app."
        else -> e.detail ?: "Login failed (${e.code})."
    }
}
