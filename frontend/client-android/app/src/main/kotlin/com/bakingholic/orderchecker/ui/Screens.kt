package com.bakingholic.orderchecker.ui

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.bakingholic.orderchecker.settings.PinGate
import kotlinx.coroutines.withTimeoutOrNull

/** The version label; a 5 s press opens the hidden settings (P-13). */
@Composable
fun VersionLabel(text: String, onLongHold: () -> Unit) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier
            .testTag("version_label")
            .padding(8.dp)
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown()
                    val released = withTimeoutOrNull(PinGate.LONG_PRESS_MILLIS) { waitForUpOrCancellation() }
                    if (released == null) onLongHold()
                }
            },
    )
}
