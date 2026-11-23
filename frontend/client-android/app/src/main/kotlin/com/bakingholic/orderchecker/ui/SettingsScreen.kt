package com.bakingholic.orderchecker.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.settings.PinGate
import com.bakingholic.orderchecker.ui.scan.ScannerTest

/** Hidden settings: PIN first, then the server profile and device information. */
@Composable
fun SettingsScreen(
    pinGate: PinGate,
    profile: ServerProfile,
    appVersion: String,
    deviceInfo: String,
    onSave: (ServerProfile, (String?) -> Unit) -> Unit,
    onCheckUpdate: () -> Unit,
    onClose: () -> Unit,
    scanSuffix: ScanSuffix = ScanSuffix.ENTER,
    onScanSuffixChange: (ScanSuffix) -> Unit = {},
) {
    var unlocked by remember { mutableStateOf(false) }
    Column(
        modifier = Modifier.fillMaxWidth().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        if (!unlocked) {
            var pin by remember { mutableStateOf("") }
            var wrong by remember { mutableStateOf(false) }
            if (!pinGate.enabled) Text("Settings are disabled in this build.")
            OutlinedTextField(
                value = pin,
                onValueChange = { pin = it },
                label = { Text("PIN") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                modifier = Modifier.testTag("pin"),
            )
            if (wrong) Text("Wrong PIN", color = MaterialTheme.colorScheme.error)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { if (pinGate.accepts(pin)) unlocked = true else wrong = true }, modifier = Modifier.testTag("unlock")) {
                    Text("Unlock")
                }
                OutlinedButton(onClick = onClose) { Text("Cancel") }
            }
            return@Column
        }
        var primary by remember { mutableStateOf(profile.primary) }
        var fallback by remember { mutableStateOf(profile.fallback.orEmpty()) }
        var clientId by remember { mutableStateOf(profile.accessClientId.orEmpty()) }
        var clientSecret by remember { mutableStateOf(profile.accessClientSecret.orEmpty()) }
        var message by remember { mutableStateOf<String?>(null) }
        Text("App $appVersion")
        Text(deviceInfo)
        OutlinedTextField(primary, { primary = it }, label = { Text("Primary address") }, singleLine = true, modifier = Modifier.fillMaxWidth().testTag("primary"))
        OutlinedTextField(fallback, { fallback = it }, label = { Text("Fallback address (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(clientId, { clientId = it }, label = { Text("Access client id (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(
            clientSecret,
            { clientSecret = it },
            label = { Text("Access client secret (optional)") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        message?.let { Text(it) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = {
                    val updated = ServerProfile(
                        primary = primary.trim(),
                        fallback = fallback.trim().ifBlank { null },
                        accessClientId = clientId.trim().ifBlank { null },
                        accessClientSecret = clientSecret.trim().ifBlank { null },
                    )
                    onSave(updated) { error -> message = error ?: "Saved" }
                },
                modifier = Modifier.testTag("save_profile"),
            ) { Text("Save") }
            OutlinedButton(onClick = onCheckUpdate) { Text("Check for update now") }
        }
        ScannerTest(scanSuffix, onScanSuffixChange)
        OutlinedButton(onClick = onClose, modifier = Modifier.testTag("close_settings")) { Text("Close") }
    }
}
