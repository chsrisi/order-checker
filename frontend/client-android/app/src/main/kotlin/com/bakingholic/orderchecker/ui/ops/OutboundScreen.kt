package com.bakingholic.orderchecker.ui.ops

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

/**
 * The label scan an admin later matches against the picking. Its own screen since Picking has the
 * Input and List tabs (V2_PICKING_DELTA Round 4).
 */
@Composable
fun OutboundScreen(ops: OpsController, suffix: ScanSuffix) {
    val outbounds by ops.repo.outbounds.collectAsStateWithLifecycle()
    val saving by ops.saving.collectAsStateWithLifecycle()
    var tag by rememberSaveable { mutableStateOf<String?>(null) }
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    val tags = outbounds.flatMap { it.tags.orEmpty() }.distinct()
    val shown = outbounds.filter { tag == null || it.tags.orEmpty().contains(tag) }
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ScanField(state = scan, suffix = suffix, label = "Scan shipping label", enabled = !saving, onScan = { ops.outbound(it.value) })
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            item { FilterChip(selected = tag == null, onClick = { tag = null }, label = { Text("All") }) }
            items(tags) { t -> FilterChip(selected = tag == t, onClick = { tag = if (tag == t) null else t }, label = { Text(t) }) }
        }
        if (shown.isEmpty()) Text("No items scanned yet")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(shown, key = { it.id }) { item ->
                Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Row {
                        Text(item.content, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Text(item.tags.orEmpty().joinToString(" "), style = MaterialTheme.typography.bodySmall)
                    }
                    Text(item.createdAt.replace('T', ' ').take(19) + " UTC", style = MaterialTheme.typography.bodySmall)
                }
                HorizontalDivider()
            }
        }
    }
}
