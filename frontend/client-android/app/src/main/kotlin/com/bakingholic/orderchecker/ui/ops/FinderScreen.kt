package com.bakingholic.orderchecker.ui.ops

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

/** Item finder, copied from v1 (Q31): scan or type a SKU or name, see where it is. Map later (D7). */
@Composable
fun FinderScreen(ops: OpsController, suffix: ScanSuffix) {
    val found by ops.found.collectAsStateWithLifecycle()
    val saving by ops.saving.collectAsStateWithLifecycle()
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ScanField(state = scan, suffix = suffix, label = "Scan or type SKU / name", enabled = !saving, onScan = { ops.find(it.value) })
        LazyColumn {
            items(found.orEmpty(), key = { it.sku + it.location }) { item ->
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    Text(item.sku, fontWeight = FontWeight.SemiBold)
                    Text(item.itemName ?: "Unknown item")
                    Text("📍 ${item.location ?: "No location"}", style = MaterialTheme.typography.titleMedium)
                }
                HorizontalDivider()
            }
        }
    }
}
