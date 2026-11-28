package com.bakingholic.orderchecker.ui.scan

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.nativeKeyCode
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.key.utf16CodePoint
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.bakingholic.orderchecker.scan.Scan
import com.bakingholic.orderchecker.scan.ScanEnding
import com.bakingholic.orderchecker.scan.ScanFeedback
import com.bakingholic.orderchecker.scan.ScanGate
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.scan.splitInline
import com.bakingholic.orderchecker.scan.suffixEnding
import com.bakingholic.orderchecker.scan.typedText

/** State of one [ScanField]; screens keep it to show feedback and take focus back after a dialog. */
@Stable
class ScanFieldState(val gate: ScanGate = ScanGate()) {
    var text by mutableStateOf(TextFieldValue(""))
        internal set
    var feedback by mutableStateOf<ScanFeedback>(ScanFeedback.None)
    internal var focusTick by mutableIntStateOf(0)
    internal val focus = FocusRequester()

    /** The operator chose to type (the "Type" button or a tap): the soft keyboard may stay open. */
    internal var typing by mutableStateOf(false)

    /** Kept text ([ScanField] `keepText`) that the next scan replaces. */
    internal var replaceNext by mutableStateOf(false)

    /** Empties the field and takes the focus back. */
    fun clear() {
        text = TextFieldValue("")
        replaceNext = false
        typing = false
        refocus()
    }

    /** Puts the cursor back into the field (after a dialog, a sheet, or a screen change). */
    fun refocus() {
        focusTick++
    }
}

@Composable
fun rememberScanFieldState(): ScanFieldState = remember { ScanFieldState() }

/**
 * The input every scanning screen uses (T6.15a, V2_UX §2.1): a focused field that submits on the
 * configured wedge [suffix], clears itself and keeps focus, and does not open the soft keyboard
 * unless asked ("Type" button or a tap on the field). [acceptAnySuffix] is for the scanner test.
 * [keepText] leaves the submitted text in the field (search, SKU) until the next scan replaces it.
 * [refocusAfterScan] returns false when the screen moved focus elsewhere in [onScan].
 */
@Composable
fun ScanField(
    state: ScanFieldState,
    suffix: ScanSuffix,
    label: String,
    onScan: (Scan) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    acceptAnySuffix: Boolean = false,
    keepText: Boolean = false,
    refocusAfterScan: () -> Boolean = { true },
) {
    val keyboard = LocalSoftwareKeyboardController.current
    val haptics = LocalHapticFeedback.current

    val interactions = remember { MutableInteractionSource() }

    fun submit(raw: String, ending: ScanEnding, keep: String = "") {
        val shown = if (keepText) raw.trim() else keep
        state.text = TextFieldValue(shown, TextRange(shown.length))
        state.replaceNext = keepText
        state.typing = false
        val accepted = state.gate.accept(raw)?.also { onScan(Scan(it, ending)) }
        // A screen may move on to another field after a scan (v1: SKU → quantity).
        if (accepted == null || refocusAfterScan()) state.refocus()
    }

    LaunchedEffect(state.focusTick) { runCatching { state.focus.requestFocus() } }
    LifecycleResumeEffect(Unit) {
        state.refocus()
        onPauseOrDispose { }
    }
    // While scanning the field is read-only: it opens no input session, so the soft keyboard
    // cannot appear (an editable field asks for it on hardware keys, seen on the emulator), and
    // the scanned characters are taken from the key events below. Typing by hand (a tap or the
    // "Type" button) switches to a normal editable field with the keyboard.
    LaunchedEffect(state.typing) {
        if (state.typing) {
            runCatching { state.focus.requestFocus() }
            keyboard?.show()
        }
    }
    LaunchedEffect(interactions) {
        interactions.interactions.collect { if (it is PressInteraction.Press) state.typing = true }
    }
    LaunchedEffect(state.feedback) {
        if (state.feedback is ScanFeedback.Error) haptics.performHapticFeedback(HapticFeedbackType.Reject)
    }

    Column(modifier = modifier) {
        OutlinedTextField(
            value = state.text,
            onValueChange = { value ->
                val (scan, rest) = splitInline(value.text, suffix, acceptAnySuffix)
                if (scan != null) submit(scan.value, scan.ending, rest) else { state.text = value; state.replaceNext = false }
            },
            label = { Text(label) },
            singleLine = true,
            enabled = enabled,
            readOnly = !state.typing,
            interactionSource = interactions,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done, showKeyboardOnFocus = false),
            keyboardActions = KeyboardActions(onDone = { submit(state.text.text, ScanEnding.IME) }),
            trailingIcon = {
                TextButton(onClick = { state.typing = true }, enabled = enabled) { Text("Type") }
            },
            modifier = Modifier
                .fillMaxWidth()
                .focusRequester(state.focus)
                .onPreviewKeyEvent { event ->
                    val ending = suffixEnding(event.key.nativeKeyCode, suffix, acceptAnySuffix)
                    if (ending == null) {
                        if (state.typing || event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                        val typed = typedText(if (state.replaceNext) "" else state.text.text, event.key.nativeKeyCode, event.utf16CodePoint)
                            ?: return@onPreviewKeyEvent false
                        state.text = TextFieldValue(typed, TextRange(typed.length))
                        state.replaceNext = false
                        return@onPreviewKeyEvent true
                    }
                    // Consume both down and up so the suffix never moves focus or types a character.
                    if (event.type == KeyEventType.KeyDown) submit(state.text.text, ending)
                    true
                }
                .testTag("scan_field"),
        )
        FeedbackLine(state.feedback)
    }
}

@Composable
private fun FeedbackLine(feedback: ScanFeedback) {
    val (text, color) = when (feedback) {
        ScanFeedback.None -> return
        is ScanFeedback.Ok -> "✓ ${feedback.message}" to Color(0xFF2E7D32)
        is ScanFeedback.Warning -> "! ${feedback.message}" to Color(0xFFB26A00)
        is ScanFeedback.Error -> "✕ ${feedback.message}" to MaterialTheme.colorScheme.error
    }
    Text(text, color = color, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("scan_feedback"))
}
