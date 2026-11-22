package com.bakingholic.orderchecker.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.bakingholic.orderchecker.updater.UpdateState

/** True when the app must not be used until it is updated. */
fun UpdateState.blocking(): Boolean = when (this) {
    is UpdateState.Available -> required
    is UpdateState.Downloading -> required
    is UpdateState.Installing -> required
    is UpdateState.Failed -> required
    else -> false
}

@Composable
fun UpdateBlockingScreen(state: UpdateState, currentVersion: String, onUpdate: () -> Unit, onCheck: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Update required", style = MaterialTheme.typography.headlineSmall)
        Text("Installed: $currentVersion")
        UpdateProgress(state, onUpdate, onCheck)
    }
}

@Composable
fun UpdateBanner(state: UpdateState, onUpdate: () -> Unit, onLater: () -> Unit) {
    val show = when (state) {
        is UpdateState.Available, is UpdateState.Downloading, is UpdateState.Installing -> true
        is UpdateState.Failed -> state.release != null
        else -> false
    }
    if (!show) return
    Card(modifier = Modifier.fillMaxWidth().padding(8.dp).testTag("update_banner")) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            UpdateProgress(state, onUpdate, onCheck = {}, onLater = onLater)
        }
    }
}

@Composable
private fun UpdateProgress(state: UpdateState, onUpdate: () -> Unit, onCheck: () -> Unit, onLater: (() -> Unit)? = null) {
    when (state) {
        is UpdateState.Available -> {
            Text("Version ${state.release.versionName} is available." + (state.release.notes?.let { "\n$it" } ?: ""))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onUpdate, modifier = Modifier.testTag("update_now")) { Text("Update") }
                if (onLater != null && !state.required) OutlinedButton(onClick = onLater) { Text("Later") }
            }
        }
        is UpdateState.Downloading -> {
            Text("Downloading ${state.release.versionName}…")
            LinearProgressIndicator(progress = { state.progress }, modifier = Modifier.fillMaxWidth())
        }
        is UpdateState.Installing -> Text("Installing ${state.release.versionName}: confirm on the Android prompt.")
        is UpdateState.Failed -> {
            Text(state.reason, color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("update_error"))
            Button(onClick = onUpdate) { Text("Try again") }
        }
        is UpdateState.Unreachable -> {
            Text("Server unreachable; retrying automatically.")
            OutlinedButton(onClick = onCheck) { Text("Check again") }
        }
        UpdateState.Checking -> Text("Checking for updates…")
        UpdateState.Idle, UpdateState.UpToDate -> OutlinedButton(onClick = onCheck) { Text("Check again") }
    }
}
