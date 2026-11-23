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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.api.model.StockCreate
import com.bakingholic.orderchecker.ops.locationsFor
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

/**
 * Stockkeeping, copied from v1 (Q31). Fixed on the way: Enter in the location fields only moves
 * on, it no longer runs "Set" (C11). Add and Set are buttons only.
 */
@Composable
fun StockScreen(ops: OpsController, suffix: ScanSuffix) {
    val stocks by ops.repo.stocks.collectAsStateWithLifecycle()
    val saving by ops.saving.collectAsStateWithLifecycle()
    var sku by rememberSaveable { mutableStateOf("") }
    var qty by rememberSaveable { mutableStateOf("") }
    var location by rememberSaveable { mutableStateOf("") }
    var move by rememberSaveable { mutableStateOf(false) }
    var dest by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf("") }
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    val qtyFocus = remember { FocusRequester() }
    val locFocus = remember { FocusRequester() }
    val destFocus = remember { FocusRequester() }
    val known = locationsFor(stocks, sku)

    fun submit(mode: StockCreate.Mode) {
        val amount = qty.trim().toIntOrNull()
        if (sku.isBlank() || amount == null) {
            scan.feedback = com.bakingholic.orderchecker.scan.ScanFeedback.Error("Please enter valid SKU and Qty.")
            return
        }
        ops.updateStock(sku, amount, mode, location.trim().ifEmpty { null }, if (move) dest.trim().ifEmpty { null } else null) {
            sku = ""; qty = ""; location = ""; dest = ""; move = false
            scan.feedback = com.bakingholic.orderchecker.scan.ScanFeedback.None
            scan.refocus()
        }
    }

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ScanField(state = scan, suffix = suffix, label = if (sku.isEmpty()) "Scan SKU" else "SKU: $sku (scan to replace)", enabled = !saving, refocusAfterScan = { false }, onScan = { s ->
            sku = s.value
            // v1: the location of the first matching stock row is filled in.
            location = stocks.firstOrNull { it.sku.equals(s.value, true) }?.location.orEmpty()
            runCatching { qtyFocus.requestFocus() }
        })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = qty, onValueChange = { v -> qty = v.filter { it.isDigit() || it == '-' } },
                label = { Text("Qty") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
                keyboardActions = KeyboardActions(onNext = { runCatching { locFocus.requestFocus() } }),
                modifier = Modifier.weight(0.35f).focusRequester(qtyFocus).testTag("stock_qty"),
            )
            OutlinedTextField(
                value = location, onValueChange = { location = it }, label = { Text("Location") }, singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = if (move) ImeAction.Next else ImeAction.Done),
                keyboardActions = KeyboardActions(onNext = { runCatching { destFocus.requestFocus() } }, onDone = { }),
                modifier = Modifier.weight(0.65f).focusRequester(locFocus).testTag("stock_location"),
            )
        }
        if (known.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(known) { l -> AssistChip(onClick = { location = l }, label = { Text(l) }) }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = move, onCheckedChange = { on ->
                move = on
                if (on && known.none { it.equals(location.trim(), true) }) {
                    // v1: a location that holds no stock yet is the destination, not the source.
                    dest = location; location = ""
                    runCatching { locFocus.requestFocus() }
                } else if (on) {
                    runCatching { destFocus.requestFocus() }
                } else {
                    dest = ""
                }
            })
            Text("Move")
        }
        if (move) {
            OutlinedTextField(
                value = dest, onValueChange = { dest = it }, label = { Text("Move to") }, singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { }),
                modifier = Modifier.fillMaxWidth().focusRequester(destFocus),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { submit(StockCreate.Mode.ADD) }, enabled = !saving, modifier = Modifier.weight(1f).testTag("stock_add")) { Text("Add Stock") }
            OutlinedButton(onClick = { submit(StockCreate.Mode.SET) }, enabled = !saving, modifier = Modifier.weight(1f).testTag("stock_set")) { Text("Set Stock") }
        }
        HorizontalDivider()
        OutlinedTextField(value = filter, onValueChange = { filter = it }, label = { Text("Filter (SKU, name, location)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        val f = filter.trim().lowercase()
        val shown = stocks.filter { f.isEmpty() || it.sku.lowercase().contains(f) || it.itemName.orEmpty().lowercase().contains(f) || it.location.orEmpty().lowercase().contains(f) }
        if (stocks.isEmpty()) Text("No stock records found.") else if (shown.isEmpty()) Text("No items match your filter.")
        LazyColumn {
            items(shown, key = { it.id }) { s ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(s.sku, fontWeight = FontWeight.SemiBold)
                        Text("${s.itemName ?: "Unknown"} | ${s.location ?: "No Location"}", style = MaterialTheme.typography.bodySmall)
                    }
                    Text(s.stock.toString(), style = MaterialTheme.typography.titleMedium)
                }
                HorizontalDivider()
            }
        }
    }
}
