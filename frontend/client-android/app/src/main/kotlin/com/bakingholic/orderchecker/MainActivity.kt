package com.bakingholic.orderchecker

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.ui.AppViewModel
import com.bakingholic.orderchecker.ui.HomeScreen
import com.bakingholic.orderchecker.ui.LoginScreen
import com.bakingholic.orderchecker.ui.Screen
import com.bakingholic.orderchecker.ui.SettingsScreen
import com.bakingholic.orderchecker.ui.UpdateRequiredScreen
import com.bakingholic.orderchecker.ui.VersionLabel
import com.bakingholic.orderchecker.ws.WsClient

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                AppViewModel((application as OrderCheckerApp).graph) as T
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { App(viewModel) } }
    }
}

@Composable
private fun App(vm: AppViewModel) {
    val screen by vm.screen.collectAsStateWithLifecycle()
    val settingsOpen by vm.settingsOpen.collectAsStateWithLifecycle()
    val user by vm.user.collectAsStateWithLifecycle()
    val ws by vm.wsState.collectAsStateWithLifecycle()
    val onFallback by vm.onFallback.collectAsStateWithLifecycle()
    val meta by vm.meta.collectAsStateWithLifecycle()
    val graph = vm.graph
    Surface(modifier = Modifier.fillMaxSize().systemBarsPadding()) {
        Column {
            Box(modifier = Modifier.weight(1f).fillMaxSize()) {
                when {
                    settingsOpen -> SettingsScreen(
                        pinGate = graph.pinGate,
                        profile = graph.profile,
                        appVersion = graph.appInfo.label,
                        deviceInfo = "Device: not registered yet",
                        onSave = vm::saveProfile,
                        onCheckUpdate = {},
                        onClose = vm::closeSettings,
                    )
                    screen is Screen.Starting -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                    screen is Screen.Login -> LoginScreen(screen as Screen.Login, vm::login)
                    screen is Screen.Home -> HomeScreen(
                        user = user,
                        connection = when (ws) {
                            WsClient.State.CONNECTED -> "connected"
                            WsClient.State.CONNECTING -> "connecting…"
                            WsClient.State.DISCONNECTED -> "offline"
                        },
                        onFallback = onFallback,
                        stockMode = meta?.stockLocationMode,
                        onLogout = vm::logout,
                    )
                    screen is Screen.UpdateRequired -> UpdateRequiredScreen(
                        (screen as Screen.UpdateRequired).minSupportedVersionCode,
                        graph.appInfo.versionCode,
                    )
                }
            }
            Box(modifier = Modifier.fillMaxSize().weight(0.08f), contentAlignment = Alignment.Center) {
                VersionLabel(graph.appInfo.label, onLongHold = vm::openSettings)
            }
        }
    }
}
