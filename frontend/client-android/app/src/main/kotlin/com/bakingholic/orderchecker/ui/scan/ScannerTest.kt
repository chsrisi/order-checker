package com.bakingholic.orderchecker.ui.scan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.bakingholic.orderchecker.scan.ScanEnding
import com.bakingholic.orderchecker.scan.ScanFeedback
import com.bakingholic.orderchecker.scan.ScanSuffix

/**
 * Hidden-settings section: pick the wedge suffix and see what the scanner actually sends. It
 * accepts any suffix so the device-day check (V2_DEVICE_DAY_TODO §E) can read it off the screen.
 */
@Composable
fun ScannerTest(suffix: ScanSuffix, onSuffixChange: (ScanSuffix) -> Unit) {
    val state = rememberScanFieldState()
    val log = remember { mutableStateListOf<String>() }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Scanner", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Suffix:")
            ScanSuffix.entries.forEach { option ->
                FilterChip(
                    selected = option == suffix,
                    onClick = { onSuffixChange(option) },
                    label = { Text(option.label) },
                    modifier = Modifier.testTag("suffix_${option.name}"),
                )
            }
        }
        ScanField(state, suffix, label = "Scan a test barcode", acceptAnySuffix = true, onScan = { scan ->
            val matches = when (scan.ending) {
                ScanEnding.ENTER, ScanEnding.INLINE_NEWLINE -> suffix == ScanSuffix.ENTER
                ScanEnding.TAB, ScanEnding.INLINE_TAB -> suffix == ScanSuffix.TAB
                ScanEnding.IME -> true
            }
            log.add(0, "${scan.value} · ${scan.value.length} chars · ended by ${scan.ending.label}")
            if (log.size > 5) log.removeAt(log.lastIndex)
            state.feedback = if (matches) {
                ScanFeedback.Ok("Read ${scan.value}")
            } else {
                ScanFeedback.Warning("Scanner sends ${scan.ending.label}; the setting is ${suffix.label}")
            }
        })
        log.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
}
