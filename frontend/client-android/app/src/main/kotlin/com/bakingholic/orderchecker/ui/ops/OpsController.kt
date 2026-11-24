package com.bakingholic.orderchecker.ui.ops

import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.api.model.StockCreate
import com.bakingholic.orderchecker.api.model.WarehouseItemResponse
import com.bakingholic.orderchecker.ops.ActionResult
import com.bakingholic.orderchecker.ops.ORDER_SN_PATTERN
import com.bakingholic.orderchecker.ops.OpsRepository
import com.bakingholic.orderchecker.ops.displayCode
import com.bakingholic.orderchecker.ops.pickWarning
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * A message for the operator, shown like v1 (kept on purpose, V2_DELTA D8 / Q31): [alert] as a
 * dialog that must be dismissed, otherwise a snackbar.
 */
data class UiMessage(val text: String, val isError: Boolean = false, val alert: Boolean = false)

/**
 * The operator actions of the scaffold screens (V2_UX §2.2), with v1's messages. Lives in the
 * view model, so the selected order survives leaving the Orders screen (C4).
 */
class OpsController(val repo: OpsRepository, private val scope: CoroutineScope) {
    private val _selectedOrder = MutableStateFlow<String?>(null)
    val selectedOrder: StateFlow<String?> = _selectedOrder
    private val _messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val messages: SharedFlow<UiMessage> = _messages

    /** A blocking progress text ("order not found, attempting backend refresh"), or null. */
    private val _blocking = MutableStateFlow<String?>(null)
    val blocking: StateFlow<String?> = _blocking
    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving
    private val _found = MutableStateFlow<List<WarehouseItemResponse>?>(null)
    val found: StateFlow<List<WarehouseItemResponse>?> = _found

    /** Bumped when a pop-up closes: the visible screen puts the cursor back into its scan field. */
    private val _refocus = MutableStateFlow(0)
    val refocus: StateFlow<Int> = _refocus

    fun requestRefocus() {
        _refocus.value++
    }

    private fun say(text: String, isError: Boolean = false, alert: Boolean = false) {
        _messages.tryEmit(UiMessage(text, isError, alert))
    }

    /** v1's failure handling: 409 (duplicate) as an alert with the server's detail. */
    private fun failed(result: ActionResult.Failed, fallback: String) = when {
        result.code == 0 -> say("Cannot connect to server. Please check your network connection.", isError = true)
        result.code == 409 -> say(result.detail, isError = true, alert = true)
        result.code >= 500 -> say("Server error occurred.", isError = true)
        else -> say("$fallback ${result.detail}".trim(), isError = true)
    }

    /** 409: what this screen shows is stale (a close is not pushed to operators), so reload it. */
    private fun orderFailed(result: ActionResult.Failed, fallback: String) {
        failed(result, fallback)
        if (result.code == 409) repo.requestSnapshots()
    }

    private fun launchSaving(block: suspend () -> Unit) {
        scope.launch {
            _saving.value = true
            try {
                block()
            } finally {
                _saving.value = false
            }
        }
    }

    /** Input shows the Item mode; only possible with a selected order (V2_PICKING_SPEC §5.1). */
    private val _itemMode = MutableStateFlow(false)
    val itemMode: StateFlow<Boolean> = _itemMode

    /** The scanned SKU waiting for its quantity, for the selected order. */
    private val _pendingSku = MutableStateFlow<String?>(null)
    val pendingSku: StateFlow<String?> = _pendingSku

    init {
        // The selected order may leave the list (done, cancelled). Right after a claim its frame
        // has not arrived yet, so it must have been in the list before.
        scope.launch {
            var previous = emptyList<ShopeeOrderResponse>()
            repo.orders.collect { orders ->
                val selected = _selectedOrder.value
                val before = previous.firstOrNull { it.orderSn == selected }
                previous = orders
                if (before != null && orders.none { it.orderSn == selected }) {
                    selectOrder(null)
                    if (repo.ordersLoaded.value) { // else: logged out
                        say("${displayCode(before)} (${before.orderSn}) is no longer in your list: it was completed, cancelled or released.", alert = true)
                    }
                }
            }
        }
    }

    fun selectOrder(orderSn: String?) {
        if (orderSn != _selectedOrder.value) _pendingSku.value = null
        _selectedOrder.value = orderSn
        _itemMode.value = orderSn != null
    }

    fun setItemMode(on: Boolean) {
        _itemMode.value = on && _selectedOrder.value != null
        _pendingSku.value = null
    }

    fun scanSku(sku: String?) {
        _pendingSku.value = sku
    }

    fun clear() {
        selectOrder(null)
        _found.value = null
        repo.clear()
    }

    /** Order mode: claim the scanned order; on 404 sync Shopee once and retry (v1). */
    fun acquire(orderSn: String) {
        if (!ORDER_SN_PATTERN.matches(orderSn)) {
            say("Invalid Order SN. Must start with YYMMDD.", isError = true, alert = true)
            return
        }
        launchSaving {
            var result = repo.acquire(orderSn)
            if (result is ActionResult.Failed && result.code == 404) {
                _blocking.value = "order not found, attempting backend refresh"
                val synced = repo.syncOrders()
                result = if (synced is ActionResult.Ok) repo.acquire(orderSn) else result
                _blocking.value = null
                if (result is ActionResult.Failed && result.code == 404) {
                    say("order not found, please have a check", isError = true, alert = true)
                    return@launchSaving
                }
            }
            when (result) {
                is ActionResult.Ok -> {
                    say("Order acquired successfully.")
                    selectOrder(orderSn)
                }
                is ActionResult.Failed -> failed(result, "Failed to acquire order.")
            }
        }
    }

    /** Item mode: picks the pending SKU into the selected order; warns, never blocks (Q63). */
    fun pick(qty: Int) {
        val orderSn = _selectedOrder.value ?: return say("No order selected.", alert = true)
        val sku = _pendingSku.value ?: return
        _pendingSku.value = null
        launchSaving {
            when (val result = repo.pick(orderSn, sku, qty)) {
                is ActionResult.Ok -> {
                    val order = repo.orders.value.firstOrNull { it.orderSn == orderSn }
                    val warning = order?.let { pickWarning(it, result.value.sku, result.value.qty) }
                    if (warning != null) say(warning, alert = true) else say("Scan entry posted.")
                }
                is ActionResult.Failed -> orderFailed(result, "Failed to post scan entry.")
            }
        }
    }

    /** Takes a quantity off an order; it goes back to stock at once. */
    fun unassign(orderSn: String, sku: String, qty: Int) = launchSaving {
        when (val r = repo.unassign(orderSn, sku, qty)) {
            is ActionResult.Ok -> say("Returned $qty × $sku to stock.")
            is ActionResult.Failed -> orderFailed(r, "Failed to unassign.")
        }
    }

    fun outbound(content: String) = launchSaving {
        when (val r = repo.outbound(content)) {
            is ActionResult.Ok -> say("Item saved successfully.")
            is ActionResult.Failed -> failed(r, "Failed to save item.")
        }
    }

    fun updateStock(sku: String, qty: Int, mode: StockCreate.Mode, location: String?, moveTo: String?, onDone: () -> Unit) =
        launchSaving {
            when (val r = repo.updateStock(sku, qty, mode, location, moveTo)) {
                is ActionResult.Ok -> {
                    say("Stock updated.")
                    onDone()
                }
                is ActionResult.Failed -> failed(r, "Failed to update stock.")
            }
        }

    fun find(query: String) = launchSaving {
        when (val r = repo.findItems(query)) {
            is ActionResult.Ok -> {
                _found.value = r.value
                if (r.value.isEmpty()) say("No items found.")
            }
            is ActionResult.Failed -> failed(r, "Search failed.")
        }
    }
}
