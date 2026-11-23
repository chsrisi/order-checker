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
import com.bakingholic.orderchecker.device.DeviceStatus
import com.bakingholic.orderchecker.ui.AppViewModel
import com.bakingholic.orderchecker.ui.ops.InfoRow
import com.bakingholic.orderchecker.ui.ops.MainShell
import com.bakingholic.orderchecker.ui.LoginScreen
import com.bakingholic.orderchecker.ui.Screen
import com.bakingholic.orderchecker.ui.SettingsScreen
import com.bakingholic.orderchecker.ui.UpdateBanner
import com.bakingholic.orderchecker.ui.UpdateBlockingScreen
import com.bakingholic.orderchecker.ui.blocking
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

    override fun onResume() {
        super.onResume()
        viewModel.checkForUpdate(minIntervalMillis = 60_000) // T6.12: also on resume
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
    val update by vm.updateState.collectAsStateWithLifecycle()
    val device by vm.deviceStatus.collectAsStateWithLifecycle()
    val scanSuffix by vm.scanSuffix.collectAsStateWithLifecycle()
    val graph = vm.graph
    Surface(modifier = Modifier.fillMaxSize().systemBarsPadding()) {
        Column {
            if (!update.blocking() && !settingsOpen) UpdateBanner(update, vm::installUpdate, vm::postponeUpdate)
            Box(modifier = Modifier.weight(1f).fillMaxSize()) {
                when {
                    settingsOpen -> SettingsScreen(
                        pinGate = graph.pinGate,
                        profile = graph.profile,
                        appVersion = graph.appInfo.label,
                        deviceInfo = "Device: " + deviceLine(device),
                        onSave = vm::saveProfile,
                        onCheckUpdate = { vm.checkForUpdate() },
                        onClose = vm::closeSettings,
                        scanSuffix = scanSuffix,
                        onScanSuffixChange = vm::setScanSuffix,
                    )
                    update.blocking() -> UpdateBlockingScreen(update, graph.appInfo.label, vm::installUpdate, vm::checkForUpdate)
                    screen is Screen.Starting -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                    screen is Screen.Login -> LoginScreen(screen as Screen.Login, vm::login)
                    screen is Screen.Home -> MainShell(
                        ops = vm.ops,
                        username = user,
                        scanSuffix = scanSuffix,
                        onFallback = onFallback,
                        deviceInfo = listOfNotNull(
                            InfoRow("Logged in as", user ?: "—"),
                            InfoRow("Device", deviceLine(device)),
                            InfoRow("App", graph.appInfo.label),
                            meta?.let { InfoRow("Server", "${it.apiVersion} · ${it.appEnv}") },
                            meta?.let { InfoRow("Stock mode", it.stockLocationMode) },
                            meta?.let { InfoRow("Contract", "${it.clientContract.min}–${it.clientContract.max}") },
                            InfoRow(
                                "Live updates",
                                when (ws) {
                                    WsClient.State.CONNECTED -> "connected"
                                    WsClient.State.CONNECTING -> "connecting…"
                                    WsClient.State.DISCONNECTED -> "offline"
                                },
                            ),
                            InfoRow("Network", if (onFallback) "LAN fallback" else "primary"),
                        ),
                        onLogout = vm::logout,
                        footer = { },
                    )
                    screen is Screen.UpdateRequired -> UpdateBlockingScreen(update, graph.appInfo.label, vm::installUpdate, vm::checkForUpdate)
                }
            }
            Box(modifier = Modifier.fillMaxSize().weight(0.08f), contentAlignment = Alignment.Center) {
                VersionLabel(graph.appInfo.label, onLongHold = vm::openSettings)
            }
        }
    }
}

private fun deviceLine(device: DeviceStatus): String = when (device) {
    DeviceStatus.Unregistered -> "not registered (log in first)"
    DeviceStatus.Registering -> "registering…"
    is DeviceStatus.Retrying -> "registration pending (${device.reason}); retrying"
    is DeviceStatus.Registered -> "${device.deviceId.take(8)} · ${device.status}"
    DeviceStatus.Revoked -> "REVOKED by the admin"
    is DeviceStatus.Rejected -> "registration refused (${device.reason})"
}
