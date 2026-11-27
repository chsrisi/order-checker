package com.bakingholic.orderchecker.ui.ops

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
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
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.api.model.TaskResponse
import com.bakingholic.orderchecker.ops.CANT_FINISH_REASONS
import com.bakingholic.orderchecker.ops.LineState
import com.bakingholic.orderchecker.ops.OrderState
import com.bakingholic.orderchecker.ops.StockAction
import com.bakingholic.orderchecker.ops.StockFlow
import com.bakingholic.orderchecker.ops.StockLock
import com.bakingholic.orderchecker.ops.StockStep
import com.bakingholic.orderchecker.ops.TaskEntry
import com.bakingholic.orderchecker.ops.countLine
import com.bakingholic.orderchecker.ops.describeTask
import com.bakingholic.orderchecker.ops.displayCode
import com.bakingholic.orderchecker.ops.leaves
import com.bakingholic.orderchecker.ops.lineState
import com.bakingholic.orderchecker.ops.pickedExactly
import com.bakingholic.orderchecker.ops.progressLabel
import com.bakingholic.orderchecker.ops.recordedLocations
import com.bakingholic.orderchecker.ops.taskEntries
import com.bakingholic.orderchecker.ops.validQty
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

private val green = Color(0xFF2E7D32)
private val amber = Color(0xFFB26A00)
private val submitOrange = Color(0xFFB45309)

/** The worker's tasks and claimed orders (T9.4, V2_UX §2.9), live from `tasks_update`. */
@Composable
fun TasksScreen(ops: OpsController, suffix: ScanSuffix, onOpenOrder: (String) -> Unit) {
    val tasks by ops.repo.tasks.collectAsStateWithLifecycle()
    val orders by ops.repo.orders.collectAsStateWithLifecycle()
    val picks by ops.repo.picks.collectAsStateWithLifecycle()
    var openId by rememberSaveable { mutableStateOf<Int?>(null) }
    val open = tasks.firstOrNull { it.id == openId }

    // A task that leaves the list (done, cancelled, reassigned) closes its screen.
    LaunchedEffect(openId, open) { if (openId != null && open == null) openId = null }
    if (open != null) {
        BackHandler { openId = null }
        key(open.id) {
            when (open.type) {
                TaskResponse.Type.COUNT -> CountTaskScreen(open, ops, suffix, onClose = { openId = null })
                TaskResponse.Type.PICK -> PickTaskScreen(open, ops, suffix, onClose = { openId = null })
            }
        }
        return
    }

    val entries = taskEntries(tasks, orders, picks)
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Spacer8() }
        if (entries.isEmpty()) item { Text("Nothing to do right now.", Modifier.padding(8.dp).testTag("tasks_empty")) }
        items(entries, key = { e -> if (e is TaskEntry.Manual) "t${e.task.id}" else "o${(e as TaskEntry.Order).order.orderSn}" }) { entry ->
            when (entry) {
                is TaskEntry.Manual -> TaskRow(entry.task, onClick = { openId = entry.task.id })
                is TaskEntry.Order -> OrderTaskRow(entry, onClick = { onOpenOrder(entry.order.orderSn) })
            }
        }
        item { Spacer8() }
    }
}

@Composable
private fun Spacer8() = Box(Modifier.padding(top = 4.dp))

@Composable
private fun TaskRow(task: TaskResponse, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick).testTag("task_${task.id}")) {
        Column(Modifier.padding(12.dp)) {
            Text(describeTask(task), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium)
            task.note?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            when {
                task.status == TaskResponse.Status.BLOCKED ->
                    Text("Blocked: ${task.blockedReason ?: ""} · waiting for the admin", color = MaterialTheme.colorScheme.error, fontWeight = FontWeight.SemiBold)
                task.inProgress -> Text("In progress", color = amber, fontWeight = FontWeight.SemiBold)
                else -> Text("To do", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun OrderTaskRow(entry: TaskEntry.Order, onClick: () -> Unit) {
    val color = when (entry.progress.state) {
        OrderState.PARTIAL -> amber
        OrderState.EXTRA -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick).testTag("order_task_${entry.order.orderSn}")) {
        Column(Modifier.padding(12.dp)) {
            Text("Order", style = MaterialTheme.typography.labelMedium)
            Text(displayCode(entry.order), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium)
            Text("${entry.order.orderSn} · ship by ${entry.order.shipBy.take(10)}", style = MaterialTheme.typography.bodySmall)
            Text(progressLabel(entry.progress), color = color, fontWeight = FontWeight.SemiBold)
        }
    }
}

/** Header of a task screen: what it is, the admin's note, and *Can't finish* in the ⋯ menu. */
@Composable
private fun TaskHeader(task: TaskResponse, ops: OpsController, onClose: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    var reporting by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            // The pick screen shows its progress in the lines card, so the header names the task only.
            val title = if (task.type == TaskResponse.Type.PICK) listOfNotNull("Pick", task.reference).joinToString(" · ") else describeTask(task)
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            task.note?.let { Text("Note: $it", style = MaterialTheme.typography.bodySmall) }
        }
        Box {
            TextButton(onClick = { menu = true }, modifier = Modifier.testTag("task_menu")) { Text("⋯") }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text("Can't finish…") }, onClick = { menu = false; reporting = true }, modifier = Modifier.testTag("task_cant_finish"))
            }
        }
    }
    if (reporting) {
        CantFinishDialog(
            onDismiss = { reporting = false; ops.requestRefocus() },
            onSend = { reason -> ops.blockTask(task.id, reason) { reporting = false; onClose() } },
        )
    }
}

/** Can't finish (T7, UX-T7): a quick reason or a typed one; the admin sees the text. */
@Composable
private fun CantFinishDialog(onDismiss: () -> Unit, onSend: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    val reason = text.trim().take(200)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Can't finish this task?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Say why. The admin then reassigns, cancels or closes it.")
                CANT_FINISH_REASONS.forEach { r ->
                    FilterChip(selected = text == r, onClick = { text = r }, label = { Text(r) }, modifier = Modifier.testTag("reason_$r"))
                }
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    label = { Text("Reason") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag("reason_text"),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSend(reason) }, enabled = reason.isNotEmpty(), modifier = Modifier.testTag("reason_send")) { Text("Send") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/**
 * A count task: the guided Stockkeeping Count locked to the task (V2_STOCK_DELTA R1.2), blind
 * (T6). In `single` mode the lock has no location (P-29) and the item's recorded one is
 * confirmed; an item without a location starts at the item scan.
 */
@Composable
private fun CountTaskScreen(task: TaskResponse, ops: OpsController, suffix: ScanSuffix, onClose: () -> Unit) {
    val mode by ops.stockMode.collectAsStateWithLifecycle()
    val stocks by ops.repo.stocks.collectAsStateWithLifecycle()
    val line = task.countLine() ?: return
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TaskHeader(task, ops, onClose)
        val single = when (mode) {
            "single" -> true
            "multi" -> false
            else -> null
        }
        if (single == null) {
            Text("Loading the server's stock settings…")
            return@Column
        }
        val lock = StockLock(sku = line.sku, location = if (single) null else line.location, blind = true)
        val noLocation = single && recordedLocations(stocks, line.sku).isEmpty()
        val start = StockFlow(action = StockAction.COUNT, single = single, lock = lock, step = if (noLocation) StockStep.ITEM else StockStep.LOCATION)
        GuidedStockFlow(
            start = start,
            ops = ops,
            suffix = suffix,
            onExit = onClose,
            submit = { plan, done ->
                ops.countTask(task.id, plan) { error -> done(error, if (error == null) "Counted ${plan.qty}" else null) }
            },
            onCompleted = onClose,
        )
    }
}

/**
 * A pick task on the Picking pattern: scan the SKU, the quantity, *Submit Scan*; the lines with
 * required and picked; tap a picked line to Remove it (back to stock). A task has one list of
 * lines, so there is no separate List tab.
 */
@Composable
private fun PickTaskScreen(task: TaskResponse, ops: OpsController, suffix: ScanSuffix, onClose: () -> Unit) {
    val saving by ops.saving.collectAsStateWithLifecycle()
    var open by remember { mutableStateOf<String?>(null) }
    var removing by remember { mutableStateOf<String?>(null) }
    val scan = rememberScanFieldState()
    var sku by remember { mutableStateOf<String?>(null) }
    var qty by remember { mutableStateOf(TextFieldValue("1")) }
    val qtyFocus = remember { FocusRequester() }
    RefocusOn(ops, scan)
    val amount = validQty(qty.text)
    val ready = sku != null && scan.text.text.trim() == sku && amount != null && !saving

    fun submit() {
        if (!ready) return
        ops.pickTask(task.id, sku ?: return, amount ?: return)
        sku = null
        qty = TextFieldValue("1")
        scan.clear()
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TaskHeader(task, ops, onClose)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
            ScanField(
                state = scan,
                suffix = suffix,
                label = "SKU",
                keepText = true,
                refocusAfterScan = { false },
                onScan = {
                    open = null
                    sku = it.value
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
                modifier = Modifier.weight(1f).focusRequester(qtyFocus).testTag("task_pick_qty"),
            )
        }
        Button(
            onClick = { submit() },
            enabled = ready,
            colors = ButtonDefaults.buttonColors(containerColor = submitOrange, contentColor = Color.White),
            modifier = Modifier.fillMaxWidth().testTag("task_pick_submit"),
        ) { Text("Submit Scan") }

        Card(Modifier.fillMaxWidth()) {
            Text(
                "${task.pickedExactly()}/${task.leaves().size} done",
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(12.dp),
            )
            task.leaves().forEach { line ->
                val picked = line.picked ?: 0
                val color = when (lineState(line)) {
                    LineState.DONE -> green
                    LineState.PARTIAL -> amber
                    LineState.OVER -> MaterialTheme.colorScheme.error
                    LineState.NONE -> MaterialTheme.colorScheme.onSurfaceVariant
                }
                HorizontalDivider(Modifier.padding(horizontal = 12.dp))
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp)
                        .clickable { open = line.sku.takeIf { it != open && picked > 0 } }
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                        .testTag("task_line_${line.sku}"),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(line.itemName ?: line.sku)
                        Text(line.sku, style = MaterialTheme.typography.bodySmall)
                    }
                    Text("$picked / ${line.qty ?: 0}", color = color, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 8.dp))
                }
                if (open == line.sku && picked > 0) {
                    OutlinedButton(
                        onClick = { removing = line.sku },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                        modifier = Modifier.align(Alignment.End).padding(end = 12.dp, bottom = 6.dp).testTag("task_remove"),
                    ) { Text("Remove") }
                }
            }
        }
    }

    removing?.let { lineSku ->
        val line = task.leaves().firstOrNull { it.sku == lineSku }
        val max = line?.picked ?: 0
        if (line == null || max == 0) {
            LaunchedEffect(lineSku) { removing = null; open = null; ops.requestRefocus() }
        } else {
            UnassignDialog(
                title = "Unassign from this task",
                item = "${line.sku} — ${line.itemName.orEmpty()}",
                max = max,
                onDismiss = { removing = null; ops.requestRefocus() },
                onUnassign = { n ->
                    ops.unassignTask(task.id, line.sku, n)
                    removing = null
                    open = null
                    ops.requestRefocus()
                },
            )
        }
    }
}
