package com.bakingholic.orderchecker.ui.ops

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.ops.LineState
import com.bakingholic.orderchecker.ops.OrderPick
import com.bakingholic.orderchecker.ops.OrderState
import com.bakingholic.orderchecker.ops.displayCode
import com.bakingholic.orderchecker.ops.matchesOrder
import com.bakingholic.orderchecker.ops.progress
import com.bakingholic.orderchecker.ops.progressLabel
import com.bakingholic.orderchecker.ops.splitPicked
import com.bakingholic.orderchecker.ops.validQty
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

private val green = Color(0xFF2E7D32)
private val amber = Color(0xFFB26A00)
private val submitOrange = Color(0xFFB45309)

/** A picked line of an order: the one showing Remove, or the one being unassigned. */
private data class LineRef(val orderSn: String, val sku: String)

/**
 * Picking (V2_PICKING_DELTA, mock r2): **Input** scans an order, then its items; **List** shows
 * every order the operator claimed. A tap on a line selects its order and offers Remove.
 */
@Composable
fun PickingScreen(ops: OpsController, suffix: ScanSuffix) {
    val orders by ops.repo.orders.collectAsStateWithLifecycle()
    val picks by ops.repo.picks.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var open by remember { mutableStateOf<LineRef?>(null) }
    var removing by remember { mutableStateOf<LineRef?>(null) }

    fun picked(ref: LineRef) = picks.filter { it.orderSn == ref.orderSn && it.sku == ref.sku }.sumOf { it.qty }

    val onLine = { orderSn: String, sku: String ->
        val ref = LineRef(orderSn, sku)
        ops.selectOrder(orderSn)
        open = ref.takeIf { it != open && picked(it) > 0 }
    }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = tab) {
            listOf("Input", "List").forEachIndexed { i, name ->
                Tab(
                    selected = tab == i,
                    onClick = { tab = i; open = null },
                    text = { Text(name) },
                    modifier = Modifier.testTag("tab_${name.lowercase()}"),
                )
            }
        }
        if (tab == 0) {
            InputTab(ops, suffix, orders, picks, open, onLine, { removing = it }, { open = null })
        } else {
            ListTab(ops, suffix, orders, picks, open, onLine, { removing = it }, { open = null })
        }
    }

    removing?.let { ref ->
        val order = orders.firstOrNull { it.orderSn == ref.orderSn }
        val max = picked(ref)
        if (order == null || max == 0) {
            // Removed elsewhere, or the order left the list: nothing to unassign any more.
            LaunchedEffect(ref) { removing = null; open = null; ops.requestRefocus() }
        } else {
            val name = progress(order, picks).lines.firstOrNull { it.sku == ref.sku }?.name.orEmpty()
            UnassignDialog(
                title = "Unassign from ${displayCode(order)}",
                item = "${ref.sku} — $name",
                max = max,
                onDismiss = { removing = null; ops.requestRefocus() },
                onUnassign = { qty ->
                    ops.unassign(ref.orderSn, ref.sku, qty)
                    removing = null
                    open = null
                    ops.requestRefocus()
                },
            )
        }
    }
}

@Composable
private fun InputTab(
    ops: OpsController,
    suffix: ScanSuffix,
    orders: List<ShopeeOrderResponse>,
    picks: List<OrderPick>,
    open: LineRef?,
    onLine: (String, String) -> Unit,
    onRemove: (LineRef) -> Unit,
    onScanned: () -> Unit,
) {
    val selected by ops.selectedOrder.collectAsStateWithLifecycle()
    val itemMode by ops.itemMode.collectAsStateWithLifecycle()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = !itemMode,
                onClick = { ops.setItemMode(false) },
                shape = SegmentedButtonDefaults.itemShape(0, 2),
                modifier = Modifier.testTag("mode_order"),
            ) { Text("Order") }
            SegmentedButton(
                selected = itemMode,
                onClick = { ops.setItemMode(true) },
                enabled = selected != null,
                shape = SegmentedButtonDefaults.itemShape(1, 2),
                modifier = Modifier.testTag("mode_item"),
            ) { Text("Item") }
        }
        if (!itemMode) {
            OrderScan(ops, suffix)
        } else {
            ItemScan(ops, suffix, onScanned)
            val order = orders.firstOrNull { it.orderSn == selected }
            if (order == null) {
                Text("No order selected", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(vertical = 8.dp))
            } else {
                OrderCard(order, picks, selected = true, open = open, onSelect = { }, onLine = onLine, onRemove = onRemove)
            }
        }
    }
}

@Composable
private fun OrderScan(ops: OpsController, suffix: ScanSuffix) {
    val saving by ops.saving.collectAsStateWithLifecycle()
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    ScanField(state = scan, suffix = suffix, label = "Scan order label", onScan = { if (!saving) ops.acquire(it.value) })
}

/** SKU and quantity side by side (v1): the SKU scan's Enter moves on to the quantity. */
@Composable
private fun ItemScan(ops: OpsController, suffix: ScanSuffix, onScanned: () -> Unit) {
    val saving by ops.saving.collectAsStateWithLifecycle()
    val pending by ops.pendingSku.collectAsStateWithLifecycle()
    val selected by ops.selectedOrder.collectAsStateWithLifecycle()
    var qty by remember(selected) { mutableStateOf(TextFieldValue("1")) }
    val scan = rememberScanFieldState()
    val qtyFocus = remember { FocusRequester() }
    RefocusOn(ops, scan)
    // A fresh field (screen opened, order changed) never shows a SKU that is not pending.
    LaunchedEffect(selected) {
        ops.scanSku(null)
        scan.clear()
    }
    val amount = validQty(qty.text)
    // The field may have been edited since the scan: submit only what it shows.
    val ready = pending != null && scan.text.text.trim() == pending && amount != null && !saving

    fun submit() {
        if (!ready) return
        ops.pick(amount ?: return)
        qty = TextFieldValue("1")
        scan.clear()
    }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        ScanField(
            state = scan,
            suffix = suffix,
            label = "SKU", // stays enabled while saving: a disabled field cannot take the focus back
            keepText = true,
            refocusAfterScan = { false },
            onScan = {
                onScanned()
                ops.scanSku(it.value)
                // v1 selects the quantity, so typing replaces it.
                qty = qty.copy(selection = TextRange(0, qty.text.length))
                runCatching { qtyFocus.requestFocus() }
            },
            modifier = Modifier.weight(2f),
        )
        OutlinedTextField(
            value = qty,
            onValueChange = { v -> qty = v.copy(text = v.text.filter(Char::isDigit)) },
            label = { Text("Qty") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { submit() }),
            modifier = Modifier.weight(1f).focusRequester(qtyFocus).testTag("pick_qty"),
        )
    }
    Button(
        onClick = { submit() },
        enabled = ready,
        colors = ButtonDefaults.buttonColors(containerColor = submitOrange, contentColor = Color.White),
        modifier = Modifier.fillMaxWidth().testTag("pick_submit"),
    ) { Text("Submit Scan") }
}

@Composable
private fun ListTab(
    ops: OpsController,
    suffix: ScanSuffix,
    orders: List<ShopeeOrderResponse>,
    picks: List<OrderPick>,
    open: LineRef?,
    onLine: (String, String) -> Unit,
    onRemove: (LineRef) -> Unit,
    onSearched: () -> Unit,
) {
    val selected by ops.selectedOrder.collectAsStateWithLifecycle()
    val scan = rememberScanFieldState()
    RefocusOn(ops, scan)
    val toggled = remember { mutableStateMapOf<String, Boolean>() } // order → expanded by hand
    val query = scan.text.text
    val (todo, done) = splitPicked(orders.filter { matchesOrder(it, picks, query) }, picks)
    val listState = rememberLazyListState()
    LaunchedEffect(Unit) {
        val rows = todo.map { it.orderSn } + (if (done.isEmpty()) emptyList() else listOf("")) + done.map { it.orderSn }
        rows.indexOf(selected ?: return@LaunchedEffect).takeIf { it >= 0 }?.let { listState.scrollToItem(it) }
    }

    @Composable
    fun card(order: ShopeeOrderResponse, picked: Boolean) {
        // Picked cards start collapsed (Q78), except in search results so the match is visible.
        val expanded = toggled[order.orderSn] ?: (!picked || query.isNotBlank())
        OrderCard(
            order, picks,
            selected = order.orderSn == selected,
            open = open,
            expanded = expanded,
            onToggle = { toggled[order.orderSn] = !expanded },
            onSelect = { ops.selectOrder(order.orderSn); onSearched() },
            onLine = onLine,
            onRemove = onRemove,
        )
    }
    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            // A scan here searches; it never selects or picks (Q77).
            ScanField(
                state = scan, suffix = suffix, label = "Scan or search orders", keepText = true,
                onScan = { onSearched() }, modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { scan.clear(); onSearched() }, modifier = Modifier.testTag("search_clear")) { Text("Clear") }
        }
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(todo, key = { it.orderSn }) { card(it, picked = false) }
            if (done.isNotEmpty()) {
                item(key = "picked_divider") {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Picked · ${done.size}", color = green, fontWeight = FontWeight.SemiBold)
                        HorizontalDivider()
                    }
                }
            }
            items(done, key = { it.orderSn }) { card(it, picked = true) }
            if (todo.isEmpty() && done.isEmpty()) {
                item(key = "empty") { Text(if (query.isBlank()) "No orders." else "No matching orders found", Modifier.padding(8.dp)) }
            }
        }
    }
}

@Composable
private fun OrderCard(
    order: ShopeeOrderResponse,
    picks: List<OrderPick>,
    selected: Boolean,
    open: LineRef?,
    onSelect: () -> Unit,
    onLine: (String, String) -> Unit,
    onRemove: (LineRef) -> Unit,
    expanded: Boolean = true,
    onToggle: (() -> Unit)? = null,
) {
    val p = progress(order, picks)
    val stateColor = when (p.state) {
        OrderState.DONE -> green
        OrderState.PARTIAL -> amber
        OrderState.EXTRA -> MaterialTheme.colorScheme.error
        OrderState.NOT_STARTED -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val code = displayCode(order)
    Card(
        modifier = Modifier.fillMaxWidth().testTag("order_${order.orderSn}").semantics { this.selected = selected },
        colors = if (selected) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer) else CardDefaults.cardColors(),
        border = if (selected) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else null,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f).clickable(onClick = onSelect).padding(12.dp)) {
                Text(code, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                Text("${order.orderSn} · ship by ${order.shipBy.take(10)}", style = MaterialTheme.typography.bodySmall)
                Text(progressLabel(p), color = stateColor, fontWeight = FontWeight.SemiBold)
            }
            if (onToggle != null) {
                TextButton(
                    onClick = onToggle,
                    modifier = Modifier.testTag("toggle_${order.orderSn}")
                        .semantics { contentDescription = if (expanded) "Hide items of $code" else "Show items of $code" },
                ) { Text(if (expanded) "▲" else "▼") }
            }
        }
        if (!expanded) return@Card
        p.lines.forEach { line ->
            val ref = LineRef(order.orderSn, line.sku)
            val color = when (line.state) {
                LineState.DONE -> green
                LineState.PARTIAL -> amber
                LineState.OVER -> MaterialTheme.colorScheme.error
                LineState.NONE -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            HorizontalDivider(Modifier.padding(horizontal = 12.dp))
            Row(
                Modifier.fillMaxWidth().heightIn(min = 48.dp)
                    .clickable { onLine(order.orderSn, line.sku) }
                    .padding(horizontal = 12.dp, vertical = 6.dp)
                    .testTag("line_${order.orderSn}_${line.sku}"),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(line.name)
                    Text(line.location?.let { "${line.sku} ($it)" } ?: line.sku, style = MaterialTheme.typography.bodySmall)
                }
                Text("${line.picked} / ${line.required}", color = color, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 8.dp))
            }
            if (open == ref && line.picked > 0) {
                OutlinedButton(
                    onClick = { onRemove(ref) },
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    modifier = Modifier.align(Alignment.End).padding(end = 12.dp, bottom = 6.dp).testTag("remove"),
                ) { Text("Remove") }
            }
        }
    }
}

/** The confirmation itself (Q71): names the item, the quantity (default: all) and the result. */
@Composable
internal fun UnassignDialog(title: String, item: String, max: Int, onDismiss: () -> Unit, onUnassign: (Int) -> Unit) {
    var text by remember { mutableStateOf(max.toString().let { TextFieldValue(it, TextRange(0, it.length)) }) }
    val focus = remember { FocusRequester() }
    val qty = validQty(text.text, max)
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(item)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { v -> text = v.copy(text = v.text.filter(Char::isDigit)) },
                        label = { Text("Quantity") },
                        singleLine = true,
                        isError = qty == null,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { qty?.let(onUnassign) }),
                        modifier = Modifier.width(120.dp).focusRequester(focus).testTag("unassign_qty"),
                    )
                    Text("of $max")
                }
                Text("Goes back to stock.", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton(onClick = { qty?.let(onUnassign) }, enabled = qty != null, modifier = Modifier.testTag("unassign_ok")) { Text("Unassign") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
