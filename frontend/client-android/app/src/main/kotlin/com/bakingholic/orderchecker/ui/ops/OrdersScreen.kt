package com.bakingholic.orderchecker.ui.ops

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.api.model.PickItemEntryResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.ops.LineState
import com.bakingholic.orderchecker.ops.OrderState
import com.bakingholic.orderchecker.ops.displayCode
import com.bakingholic.orderchecker.ops.matchesOrder
import com.bakingholic.orderchecker.ops.progress
import com.bakingholic.orderchecker.ops.progressLabel
import com.bakingholic.orderchecker.ops.unassignDefault
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

/**
 * Orders (V2_DELTA D8 / Q32): **Picking** is the main view; **Outbound** is the separate label
 * scan an admin later matches against the picking. Scaffold copied from v1 (Q31).
 */
@Composable
fun OrdersScreen(ops: OpsController, suffix: ScanSuffix) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = tab) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Picking") }, modifier = Modifier.testTag("tab_picking"))
            Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Outbound") }, modifier = Modifier.testTag("tab_outbound"))
        }
        if (tab == 0) PickingTab(ops, suffix) else OutboundTab(ops, suffix)
    }
}

private val green = Color(0xFF2E7D32)
private val amber = Color(0xFFB26A00)

@Composable
private fun PickingTab(ops: OpsController, suffix: ScanSuffix) {
    val orders by ops.repo.orders.collectAsStateWithLifecycle()
    val picks by ops.repo.picks.collectAsStateWithLifecycle()
    val selected by ops.selectedOrder.collectAsStateWithLifecycle()
    val saving by ops.saving.collectAsStateWithLifecycle()
    var itemMode by rememberSaveable { mutableStateOf(false) }
    var qty by remember { mutableStateOf(TextFieldValue("1")) }
    var pendingSku by rememberSaveable { mutableStateOf<String?>(null) }
    var search by rememberSaveable { mutableStateOf("") }
    var confirmDelete by remember { mutableStateOf<PickItemEntryResponse?>(null) }
    var unassign by remember { mutableStateOf<Triple<String, String, Int>?>(null) } // order, sku, default
    var assignEntry by remember { mutableStateOf<PickItemEntryResponse?>(null) }
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    val qtyFocus = remember { FocusRequester() }
    val active = orders.firstOrNull { it.orderSn == selected }

    fun submitPick() {
        val sku = pendingSku ?: return
        ops.pick(sku, qty.text.trim().toIntOrNull() ?: 1)
        pendingSku = null
        qty = TextFieldValue("1")
        scan.refocus()
    }

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                SegmentedButton(selected = !itemMode, onClick = { itemMode = false; scan.refocus() }, shape = SegmentedButtonDefaults.itemShape(0, 2)) { Text("Order") }
                SegmentedButton(selected = itemMode, onClick = { itemMode = true; scan.refocus() }, shape = SegmentedButtonDefaults.itemShape(1, 2)) { Text("Item") }
            }
        }
        item {
            ScanField(
                state = scan,
                suffix = suffix,
                label = if (itemMode) "Scan item SKU" else "Scan order label",
                enabled = !saving,
                refocusAfterScan = { !itemMode },
                onScan = { s ->
                    if (itemMode) {
                        // v1: the SKU scan's Enter moves on to the quantity; Enter there submits.
                        pendingSku = s.value
                        // v1 selects the quantity, so typing replaces it.
                        qty = qty.copy(selection = TextRange(0, qty.text.length))
                        runCatching { qtyFocus.requestFocus() }
                    } else {
                        ops.acquire(s.value) { itemMode = true }
                    }
                },
            )
        }
        if (itemMode) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(pendingSku?.let { "SKU: $it" } ?: "Scan a SKU", modifier = Modifier.weight(1f))
                    OutlinedTextField(
                        value = qty,
                        onValueChange = { v -> qty = v.copy(text = v.text.filter(Char::isDigit)) },
                        label = { Text("Qty") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { submitPick() }),
                        modifier = Modifier.width(110.dp).focusRequester(qtyFocus).testTag("pick_qty"),
                    )
                    TextButton(onClick = { submitPick() }, enabled = pendingSku != null && !saving) { Text("Submit") }
                }
            }
        }
        item {
            if (active == null) {
                Text("No order selected", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(vertical = 8.dp))
            } else {
                OrderCard(active, picks, selected = true, onClick = { }, onUnassign = { sku, def -> unassign = Triple(active.orderSn, sku, def) })
            }
        }
        val unknown = picks.filter { it.orderSn == null && it.qty > 0 }
        if (unknown.isNotEmpty()) {
            item { Text("Unassigned picks", style = MaterialTheme.typography.titleMedium) }
            items(unknown, key = { "u${it.id}" }) { entry ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(entry.sku, fontWeight = FontWeight.SemiBold)
                            Text("${entry.itemName ?: "Unknown"} | Qty: ${entry.qty}")
                        }
                        TextButton(onClick = { assignEntry = entry }) { Text("Assign") }
                        TextButton(onClick = { confirmDelete = entry }) { Text("Delete") }
                    }
                }
            }
        }
        item {
            HorizontalDivider(Modifier.padding(vertical = 4.dp))
            OutlinedTextField(
                value = search,
                onValueChange = { search = it },
                label = { Text("Search orders (SN, code, SKU, name)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        val shown = orders.filter { matchesOrder(it, picks, search) }
        items(shown, key = { it.orderSn }) { order ->
            OrderCard(order, picks, selected = order.orderSn == selected, onClick = { ops.selectOrder(order.orderSn); itemMode = true; scan.refocus() }, onUnassign = null)
        }
        if (shown.isEmpty()) item { Text("No orders.", modifier = Modifier.padding(8.dp)) }
    }

    confirmDelete?.let { entry ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Delete scan entry?") },
            text = { Text("${entry.sku} × ${entry.qty}. The stock is given back.") },
            confirmButton = { TextButton(onClick = { ops.deletePick(entry); confirmDelete = null; scan.refocus() }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { confirmDelete = null; scan.refocus() }) { Text("Cancel") } },
        )
    }
    unassign?.let { (orderSn, sku, default) ->
        var amount by remember(sku) { mutableStateOf(default.toString()) }
        AlertDialog(
            onDismissRequest = { unassign = null },
            title = { Text("Unassign SKU: $sku") },
            text = {
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it.filter(Char::isDigit) },
                    label = { Text("Move to Unknown? (Max: ${picks.filter { it.orderSn == orderSn && it.sku == sku }.sumOf { it.qty }})") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    amount.toIntOrNull()?.takeIf { it > 0 }?.let { ops.unassign(orderSn, sku, it) }
                    unassign = null
                    scan.refocus()
                }) { Text("Move") }
            },
            dismissButton = { TextButton(onClick = { unassign = null; scan.refocus() }) { Text("Cancel") } },
        )
    }
    assignEntry?.let { entry ->
        AssignDialog(entry, orders, onAssign = { order ->
            val required = order.itemList.orEmpty().firstOrNull { it.componentSku == entry.sku }?.quantity
            ops.assign(entry, order.orderSn, required)
            assignEntry = null
            scan.refocus()
        }, onDismiss = { assignEntry = null; scan.refocus() })
    }
}

@Composable
private fun AssignDialog(
    entry: PickItemEntryResponse,
    orders: List<ShopeeOrderResponse>,
    onAssign: (ShopeeOrderResponse) -> Unit,
    onDismiss: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Assign ${entry.sku} × ${entry.qty} to label") },
        text = {
            Column {
                OutlinedTextField(value = query, onValueChange = { query = it }, label = { Text("Select order") }, singleLine = true)
                orders.filter { query.isBlank() || displayCode(it).contains(query, true) || it.orderSn.contains(query, true) }
                    .take(6)
                    .forEach { order ->
                        Text(
                            "${displayCode(order)}  (${order.orderSn})",
                            modifier = Modifier.fillMaxWidth().clickable { onAssign(order) }.padding(vertical = 10.dp),
                        )
                    }
            }
        },
        confirmButton = { },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun OrderCard(
    order: ShopeeOrderResponse,
    picks: List<PickItemEntryResponse>,
    selected: Boolean,
    onClick: () -> Unit,
    onUnassign: ((String, Int) -> Unit)?,
) {
    val p = progress(order, picks)
    val stateColor = when (p.state) {
        OrderState.DONE -> green
        OrderState.PARTIAL -> amber
        OrderState.EXTRA -> MaterialTheme.colorScheme.error
        OrderState.NOT_STARTED -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).testTag("order_${order.orderSn}"),
        colors = if (selected) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer) else CardDefaults.cardColors(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(displayCode(order), fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(progressLabel(p), color = stateColor)
            }
            Text("${order.orderSn} · ship by ${order.shipBy.take(10)}", style = MaterialTheme.typography.bodySmall)
            if (selected || onUnassign != null) {
                p.lines.forEach { line ->
                    val color = when (line.state) {
                        LineState.DONE -> green
                        LineState.PARTIAL -> amber
                        LineState.OVER -> MaterialTheme.colorScheme.error
                        LineState.NONE -> MaterialTheme.colorScheme.onSurface
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("${line.sku} — ${line.name}", color = color)
                            line.location?.let { Text("📍 $it", style = MaterialTheme.typography.bodySmall) }
                        }
                        Text("${line.picked}/${line.required}", color = color)
                        if (onUnassign != null && line.picked > 0) {
                            TextButton(onClick = { onUnassign(line.sku, unassignDefault(line.picked, line.required)) }) { Text("Unassign") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun OutboundTab(ops: OpsController, suffix: ScanSuffix) {
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
