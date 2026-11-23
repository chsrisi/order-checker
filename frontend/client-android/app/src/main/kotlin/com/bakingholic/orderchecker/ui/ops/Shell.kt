package com.bakingholic.orderchecker.ui.ops

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.scan.ScanSuffix

/** Where the logged-in app is (V2_UX §2.2). Kept as a name so it survives rotation. */
enum class Destination(val title: String) {
    HOME("Order Checker"),
    DEVICE_INFO("Device info"),
    ORDERS("Orders"),
    STOCK("Stockkeeping"),
    FINDER("Finder"),
}

/** One row of the Device info screen. */
data class InfoRow(val label: String, val value: String)

/**
 * The logged-in app: a top bar with the title and the username (opens Device info), the home
 * menu, and the screens behind it. v1's pop-ups stay: alerts as dialogs, the rest as snackbars.
 */
@Composable
fun MainShell(
    ops: OpsController,
    username: String?,
    scanSuffix: ScanSuffix,
    deviceInfo: List<InfoRow>,
    onFallback: Boolean,
    onLogout: () -> Unit,
    footer: @Composable () -> Unit,
) {
    var destination by rememberSaveable { mutableStateOf(Destination.HOME) }
    val snackbar = remember { SnackbarHostState() }
    var alert by remember { mutableStateOf<UiMessage?>(null) }
    val blocking by ops.blocking.collectAsStateWithLifecycle()

    LaunchedEffect(ops) {
        ops.messages.collect { message ->
            if (message.alert) alert = message else snackbar.showSnackbar(message.text)
        }
    }
    BackHandler(enabled = destination != Destination.HOME) { destination = Destination.HOME }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (destination != Destination.HOME) {
                    TextButton(onClick = { destination = Destination.HOME }, modifier = Modifier.testTag("back")) { Text("←") }
                }
                Text(
                    destination.title,
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f).padding(start = 8.dp),
                )
                if (onFallback) AssistChip(onClick = {}, label = { Text("LAN") })
                TextButton(
                    onClick = { destination = Destination.DEVICE_INFO },
                    modifier = Modifier.testTag("username"),
                ) { Text(username ?: "—") }
            }
            HorizontalDivider()
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (destination) {
                    Destination.HOME -> HomeMenu(onOpen = { destination = it })
                    Destination.DEVICE_INFO -> DeviceInfoScreen(deviceInfo, onLogout)
                    Destination.ORDERS -> OrdersScreen(ops, scanSuffix)
                    Destination.STOCK -> StockScreen(ops, scanSuffix)
                    Destination.FINDER -> FinderScreen(ops, scanSuffix)
                }
            }
            footer()
        }
    }

    alert?.let { message ->
        val close = { alert = null; ops.requestRefocus() }
        AlertDialog(
            onDismissRequest = close,
            title = { Text(if (message.isError) "Error / Duplicate" else "Notification") },
            text = { Text(message.text) },
            confirmButton = { TextButton(onClick = close, modifier = Modifier.testTag("alert_ok")) { Text("OK") } },
        )
    }
    blocking?.let { text ->
        AlertDialog(
            onDismissRequest = { },
            text = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator()
                    Spacer(Modifier.width(16.dp))
                    Text(text)
                }
            },
            confirmButton = { },
        )
    }
}

@Composable
private fun HomeMenu(onOpen: (Destination) -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
    ) {
        listOf(Destination.ORDERS, Destination.STOCK, Destination.FINDER).forEach { d ->
            Button(
                onClick = { onOpen(d) },
                modifier = Modifier.fillMaxWidth().height(88.dp).testTag("home_${d.name.lowercase()}"),
            ) { Text(d.title, fontSize = 22.sp, fontWeight = FontWeight.SemiBold) }
        }
    }
}

@Composable
private fun DeviceInfoScreen(rows: List<InfoRow>, onLogout: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        rows.forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                Text(row.label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(0.4f))
                Text(row.value, modifier = Modifier.weight(0.6f).testTag("info_${row.label}"))
            }
        }
        Spacer(Modifier.height(16.dp))
        OutlinedButton(onClick = onLogout, modifier = Modifier.fillMaxWidth().testTag("logout")) { Text("Log out") }
    }
}

/** Puts the cursor back into [scan] whenever a pop-up of [ops] closed. */
@Composable
internal fun RefocusOn(ops: OpsController, scan: com.bakingholic.orderchecker.ui.scan.ScanFieldState) {
    val tick by ops.refocus.collectAsStateWithLifecycle()
    LaunchedEffect(tick) { if (tick > 0) scan.refocus() }
}
