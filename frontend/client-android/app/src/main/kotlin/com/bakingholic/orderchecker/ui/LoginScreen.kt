package com.bakingholic.orderchecker.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenu
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

/** Worker picker → password, or manual input (V2_UX §2.7). [known] is most recent first. */
@Composable
fun LoginScreen(
    state: Screen.Login,
    known: List<String>,
    onLogin: (String, String) -> Unit,
    onClearError: () -> Unit,
) {
    var form by remember { mutableStateOf(LoginForm()) }
    val go: (LoginForm) -> Unit = {
        form = it
        onClearError()
    }
    val submit: () -> Unit = {
        if (!state.busy) form.credentials(known)?.let { (name, password) -> onLogin(name, password) }
    }
    BackHandler(enabled = form.step != LoginStep.PICK) { if (!state.busy) go(form.back()) }

    Column(
        modifier = Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Order Checker", style = MaterialTheme.typography.headlineMedium)
        if (form.step == LoginStep.MANUAL) {
            OutlinedTextField(
                value = form.username,
                onValueChange = { form = form.copy(username = it) },
                label = { Text("Username") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("username"),
            )
        } else {
            WorkerPicker(form.worker(known), known, enabled = !state.busy) { go(form.pick(it)) }
        }
        if (form.step != LoginStep.PICK) {
            PasswordField(
                value = form.password,
                onValueChange = { form = form.copy(password = it) },
                onDone = submit,
                autoFocus = form.step == LoginStep.PASSWORD,
            )
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (state.busy) {
            CircularProgressIndicator()
        } else {
            Button(
                onClick = { if (form.step == LoginStep.PICK) go(form.askPassword(known)) else submit() },
                enabled = form.step != LoginStep.PICK || form.worker(known) != null,
                modifier = Modifier.fillMaxWidth().testTag("login"),
            ) { Text("Log in") }
            when (form.step) {
                LoginStep.PICK -> OutlinedButton(
                    onClick = { go(form.manual()) },
                    modifier = Modifier.fillMaxWidth().testTag("manual_input"),
                ) { Text("Manual input") }

                // TODO(V2_LOGIN_REQUEST_SPEC): enable once the backend has login requests.
                LoginStep.PASSWORD -> OutlinedButton(
                    onClick = {},
                    enabled = false,
                    modifier = Modifier.fillMaxWidth().testTag("request_login"),
                ) { Text("Ask admin to approve (coming soon)") }

                LoginStep.MANUAL -> Unit
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkerPicker(selected: String?, known: List<String>, enabled: Boolean, onPick: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val usable = enabled && known.isNotEmpty()
    ExposedDropdownMenuBox(expanded = expanded && usable, onExpandedChange = { expanded = it && usable }) {
        OutlinedTextField(
            value = selected.orEmpty(),
            onValueChange = {},
            readOnly = true,
            enabled = usable,
            singleLine = true,
            label = { Text("Worker") },
            supportingText = if (known.isEmpty()) {
                { Text("No worker has logged in on this device yet. Use manual input.") }
            } else {
                null
            },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded && usable) },
            modifier = Modifier
                .menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable, usable)
                .fillMaxWidth()
                .testTag("worker_picker"),
        )
        ExposedDropdownMenu(expanded = expanded && usable, onDismissRequest = { expanded = false }) {
            known.sortedWith(String.CASE_INSENSITIVE_ORDER).forEach { name ->
                DropdownMenuItem(
                    text = { Text(name) },
                    onClick = {
                        expanded = false
                        onPick(name)
                    },
                )
            }
        }
    }
}

@Composable
private fun PasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    onDone: () -> Unit,
    autoFocus: Boolean,
) {
    val focus = remember { FocusRequester() }
    if (autoFocus) LaunchedEffect(Unit) { focus.requestFocus() }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text("Password") },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        modifier = Modifier.fillMaxWidth().focusRequester(focus).testTag("password"),
    )
}
