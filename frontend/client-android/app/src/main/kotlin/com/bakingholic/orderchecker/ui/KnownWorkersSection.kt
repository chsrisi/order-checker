package com.bakingholic.orderchecker.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

/**
 * Hidden-settings section: the login picker's names on this device (V2_UX §2.7). Removing one
 * only edits the local list; that worker's next login adds the name again.
 */
@Composable
fun KnownWorkersSection(names: List<String>, onForget: (String) -> Unit, onForgetAll: () -> Unit) {
    var confirmAll by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Login picker workers", style = MaterialTheme.typography.titleMedium)
        if (names.isEmpty()) {
            Text("No workers have logged in on this device yet.")
            return@Column
        }
        Text("Removed names come back when that worker logs in again.", style = MaterialTheme.typography.bodySmall)
        names.forEach { name ->
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(name, modifier = Modifier.weight(1f))
                TextButton(onClick = { onForget(name) }, modifier = Modifier.testTag("forget_$name")) { Text("Remove") }
            }
        }
        OutlinedButton(onClick = { confirmAll = true }, modifier = Modifier.testTag("forget_all")) {
            Text("Remove all (${names.size})")
        }
    }
    if (confirmAll) {
        AlertDialog(
            onDismissRequest = { confirmAll = false },
            title = { Text("Remove all workers?") },
            text = { Text("The login picker starts empty. Each worker types their name once on the next login.") },
            confirmButton = {
                TextButton(onClick = { confirmAll = false; onForgetAll() }, modifier = Modifier.testTag("forget_all_confirm")) {
                    Text("Remove all")
                }
            },
            dismissButton = { TextButton(onClick = { confirmAll = false }) { Text("Cancel") } },
        )
    }
}
