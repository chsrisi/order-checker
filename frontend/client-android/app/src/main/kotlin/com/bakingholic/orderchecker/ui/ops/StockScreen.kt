package com.bakingholic.orderchecker.ui.ops

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bakingholic.orderchecker.ops.ActionResult
import com.bakingholic.orderchecker.ops.StockAction
import com.bakingholic.orderchecker.ops.StockFlow
import com.bakingholic.orderchecker.ops.StockPlan
import com.bakingholic.orderchecker.ops.StockRow
import com.bakingholic.orderchecker.ops.StockStep
import com.bakingholic.orderchecker.ops.recordedLocations
import com.bakingholic.orderchecker.scan.ScanFeedback
import com.bakingholic.orderchecker.scan.ScanSuffix
import com.bakingholic.orderchecker.ui.scan.ScanField
import com.bakingholic.orderchecker.ui.scan.rememberScanFieldState

/**
 * Stockkeeping as guided actions (T6.15e, V2_UX §2.10): Receive, Count or Move, each one step per
 * screen. The stock list that v1 had here is Finder's (T6.15d).
 */
@Composable
fun StockScreen(ops: OpsController, suffix: ScanSuffix) {
    val mode by ops.stockMode.collectAsStateWithLifecycle()
    var action by rememberSaveable { mutableStateOf<StockAction?>(null) }
    // Guessing the mode is unsafe: in `single` mode a location that differs from the record
    // merges the item's stock into it, so wait for the server's answer.
    val single = when (mode) {
        "single" -> true
        "multi" -> false
        else -> null
    }
    Column(Modifier.fillMaxSize().padding(12.dp)) {
        when {
            single == null -> Text("Loading the server's stock settings…", modifier = Modifier.testTag("stock_waiting"))
            action == null -> ActionPicker { action = it }
            else -> key(action) {
                GuidedStockFlow(
                    start = StockFlow(action = action!!, single = single),
                    ops = ops,
                    suffix = suffix,
                    onExit = { action = null },
                )
            }
        }
    }
}

@Composable
private fun ActionPicker(onPick: (StockAction) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Stockkeeping", style = MaterialTheme.typography.headlineSmall)
        StockAction.entries.forEach { a ->
            Button(onClick = { onPick(a) }, modifier = Modifier.fillMaxWidth().heightIn(min = 72.dp).testTag("stock_action_${a.name}")) {
                Column {
                    Text(a.title, style = MaterialTheme.typography.titleLarge)
                    Text(a.hint, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

/**
 * The guided steps, reusable by a count task (T9.4): pass [start] with a [StockLock] and a
 * [submit] that sends the task's count instead of a plain stock update. [submit] reports an
 * error text, or null on success with the line to show. A [com.bakingholic.orderchecker.ops.StockLock]
 * on [start] locks the scans and hides the recorded quantity.
 */
@Composable
fun GuidedStockFlow(
    start: StockFlow,
    ops: OpsController,
    suffix: ScanSuffix,
    onExit: () -> Unit,
    submit: ((StockPlan, (error: String?, result: String?) -> Unit) -> Unit)? = null,
    onCompleted: (() -> Unit)? = null,
) {
    val stocks by ops.repo.stocks.collectAsStateWithLifecycle()
    val saving by ops.saving.collectAsStateWithLifecycle()
    var flow by remember { mutableStateOf(start) }
    var result by remember { mutableStateOf<String?>(null) }
    var changed by remember { mutableStateOf(false) }

    fun back() {
        if (flow.step == StockStep.LOCATION) onExit() else flow = flow.back()
    }
    BackHandler { back() }

    fun send(plan: StockPlan) {
        result = null
        val done: (String?, String?) -> Unit = { error, line ->
            if (error != null) {
                flow = flow.copy(error = error)
            } else {
                result = line
                changed = true
                if (onCompleted != null && flow.resume == null) onCompleted() else flow = flow.next()
            }
        }
        if (submit != null) return submit(plan, done)
        ops.applyStock(plan) { r ->
            when (r) {
                is ActionResult.Ok -> done(null, resultLine(plan, r.value.stock))
                is ActionResult.Failed -> done(ops.failureText(r, "Failed to update stock."), null)
            }
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(flow.action.title, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.testTag("stock_title"))
        StepBar(flow)
        result?.let { Text("✓ $it", color = Color(0xFF2E7D32), modifier = Modifier.testTag("stock_result")) }
        key(flow.step, flow.action) {
            when (flow.step) {
                StockStep.LOCATION -> ScanStep(
                    label = locationPrompt(flow, stocks),
                    error = flow.error,
                    suffix = suffix,
                    enabled = !saving,
                    onScan = { flow = flow.scanLocation(it, stocks) },
                )
                // "Move it first" switches action: the previous result line no longer applies.
                StockStep.ITEM -> ItemStep(flow, stocks, suffix, saving, ops, onFlow = { next ->
                    if (next.action != flow.action) result = null
                    flow = next
                })
                StockStep.QUANTITY -> QuantityStep(flow, stocks, onFlow = { flow = it })
                StockStep.DESTINATION -> {
                    if (flow.single) Text("Moves all ${flow.qty} of ${flow.item?.sku} from ${flow.location}.")
                    ScanStep(
                        label = "Scan the destination shelf",
                        error = flow.error,
                        suffix = suffix,
                        enabled = !saving,
                        onScan = { flow = flow.scanDestination(it, stocks) },
                    )
                }
                StockStep.CONFIRM -> ConfirmStep(flow, stocks, saving, onConfirm = ::send)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = ::back, modifier = Modifier.testTag("stock_back")) { Text("Back") }
            if (changed && flow.lock == null) TextButton(onClick = onExit, modifier = Modifier.testTag("stock_done")) { Text("Done") }
        }
    }
}

private val STEPS = listOf("Location", "Item", "Quantity", "Confirm")

@Composable
private fun StepBar(flow: StockFlow) {
    val current = when (flow.step) {
        StockStep.LOCATION -> 0
        StockStep.ITEM -> 1
        StockStep.QUANTITY, StockStep.DESTINATION -> 2
        StockStep.CONFIRM -> 3
    }
    Text(
        STEPS.mapIndexed { i, s -> if (i == current) "● $s" else if (i < current) "✓ $s" else "○ $s" }.joinToString("  "),
        style = MaterialTheme.typography.bodySmall,
    )
    val path = listOfNotNull(flow.location, flow.item?.sku, flow.destination?.let { "→ $it" })
    if (path.isNotEmpty()) Text(path.joinToString(" › "), fontWeight = FontWeight.SemiBold, modifier = Modifier.testTag("stock_path"))
}

private fun locationPrompt(flow: StockFlow, stocks: List<StockRow>): String {
    val lock = flow.lock ?: return if (flow.action == StockAction.MOVE) "Scan the shelf to move from" else "Scan the shelf label"
    val expected = lock.location ?: recordedLocations(stocks, lock.sku).firstOrNull()
    return if (expected != null) "Scan $expected to confirm" else "Scan the shelf label"
}

@Composable
private fun ScanStep(label: String, error: String?, suffix: ScanSuffix, enabled: Boolean, onScan: (String) -> Unit) {
    val scan = rememberScanFieldState()
    LaunchedEffect(error) { scan.feedback = error?.let { ScanFeedback.Error(it) } ?: ScanFeedback.None }
    ScanField(state = scan, suffix = suffix, label = label, enabled = enabled, onScan = { onScan(it.value) })
}

@Composable
private fun ItemStep(
    flow: StockFlow,
    stocks: List<StockRow>,
    suffix: ScanSuffix,
    saving: Boolean,
    ops: OpsController,
    onFlow: (StockFlow) -> Unit,
) {
    val mismatch = flow.mismatch
    if (mismatch != null && flow.item != null) {
        val item = flow.item
        Text("${item.sku} · ${item.name ?: "Unknown item"}", fontWeight = FontWeight.SemiBold)
        Text("${item.sku} is recorded at $mismatch, not ${flow.location}.", modifier = Modifier.testTag("stock_mismatch"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onFlow(flow.useRecorded(stocks)) }, modifier = Modifier.testTag("stock_use_recorded")) { Text("Use $mismatch") }
            if (flow.action != StockAction.MOVE && flow.lock == null) {
                OutlinedButton(onClick = { flow.moveFirst(stocks)?.let(onFlow) }, modifier = Modifier.testTag("stock_move_first")) {
                    Text("Move it to ${flow.location} first")
                }
            }
        }
        return
    }
    var lookupError by remember { mutableStateOf<String?>(null) }
    ScanStep(
        label = "Scan the item",
        error = flow.error ?: lookupError,
        suffix = suffix,
        enabled = !saving,
        onScan = { raw ->
            lookupError = null
            ops.resolveItem(raw) { lookup ->
                when (lookup) {
                    is ItemLookup.Found -> onFlow(flow.chooseItem(lookup.item, stocks))
                    ItemLookup.NotFound -> lookupError = "No item matches $raw."
                    ItemLookup.Several -> lookupError = "Several items match $raw: scan the barcode or type the full SKU."
                    is ItemLookup.Failed -> lookupError = lookup.message
                }
            }
        },
    )
}

@Composable
private fun QuantityStep(flow: StockFlow, stocks: List<StockRow>, onFlow: (StockFlow) -> Unit) {
    val item = flow.item ?: return
    var text by rememberSaveable { mutableStateOf("") }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    Text(item.name ?: "Unknown item", style = MaterialTheme.typography.titleMedium)
    flow.recorded(stocks)?.let { Text("Recorded here: $it", modifier = Modifier.testTag("stock_recorded")) }
    val label = when (flow.action) {
        StockAction.RECEIVE -> "How many arrived"
        StockAction.COUNT -> "How many are there"
        StockAction.MOVE -> "How many to move"
    }
    fun next() = onFlow(flow.enterQty(text, stocks))
    OutlinedTextField(
        value = text,
        onValueChange = { v -> text = v.filter(Char::isDigit) },
        label = { Text(label) },
        singleLine = true,
        isError = flow.error != null,
        supportingText = flow.error?.let { e -> { Text(e) } },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
        keyboardActions = KeyboardActions(onNext = { next() }),
        modifier = Modifier.fillMaxWidth().focusRequester(focus).testTag("stock_qty"),
    )
    Button(onClick = ::next, modifier = Modifier.testTag("stock_qty_next")) { Text("Next") }
}

@Composable
private fun ConfirmStep(flow: StockFlow, stocks: List<StockRow>, saving: Boolean, onConfirm: (StockPlan) -> Unit) {
    val plan = flow.plan(stocks) ?: return
    Text(flow.item?.name ?: "Unknown item", style = MaterialTheme.typography.titleMedium)
    if (!flow.blind) {
        plan.changes.forEach { c ->
            Text("${c.location ?: "No location"}: ${c.before} → ${c.after} (${signed(c.after - c.before)})", modifier = Modifier.testTag("stock_change"))
        }
        // C9: the warning is written out, not only coloured.
        if (plan.large) Text("Large change: check the count.", color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("stock_large"))
    }
    flow.error?.let { Text("✕ $it", color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("stock_error")) }
    Button(onClick = { onConfirm(plan) }, enabled = !saving, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag("stock_confirm")) {
        Text(plan.label)
    }
}

private fun signed(n: Int) = if (n > 0) "+$n" else n.toString()

/** "203 · SKU-0012: 40 → 36", with the server's final quantity for the main location. */
internal fun resultLine(plan: StockPlan, serverStock: Int): String {
    val main = if (plan.moveTo != null) plan.changes.last() else plan.changes.first()
    val head = "${main.location ?: "No location"} · ${plan.sku}: ${main.before} → $serverStock"
    return if (plan.moveTo != null) "$head (moved from ${plan.location})" else head
}
