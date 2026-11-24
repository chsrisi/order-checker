package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.PickItemEntryResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse

/** One SKU line of an order: what the BOM requires and what was picked (v1 orders_view). */
data class SkuLine(val sku: String, val name: String, val location: String?, val required: Int, val picked: Int) {
    val state: LineState
        get() = when {
            picked == 0 -> LineState.NONE
            picked < required -> LineState.PARTIAL
            picked == required -> LineState.DONE
            else -> LineState.OVER
        }
}

enum class LineState { NONE, PARTIAL, DONE, OVER }

enum class OrderState { NOT_STARTED, PARTIAL, DONE, EXTRA }

data class OrderProgress(val lines: List<SkuLine>, val doneSkus: Int, val requiredSkus: Int, val state: OrderState)

/** v1 shows an empty component SKU as "unknown" and matches picks against that. */
private fun bomSku(sku: String) = sku.ifEmpty { UNKNOWN_SKU }

const val UNKNOWN_SKU = "unknown"

/** v1 rule: an order matches an order scan when the scan starts with YYMMDD. */
val ORDER_SN_PATTERN = Regex("""^\d{6}.*""")

fun displayCode(order: ShopeeOrderResponse): String =
    order.info.orEmpty().firstOrNull { !it.pickupCode.isNullOrEmpty() }?.pickupCode ?: order.orderSn

private data class Requirement(val quantity: Int, val name: String?, val location: String?)

/** BOM lines sharing a SKU are one requirement (V2_ORDERS_DELTA F2). */
private fun requirements(order: ShopeeOrderResponse): Map<String, Requirement> {
    val out = LinkedHashMap<String, Requirement>()
    order.itemList.orEmpty().forEach { b ->
        val sku = bomSku(b.componentSku)
        val prev = out[sku]
        out[sku] = prev?.copy(quantity = prev.quantity + b.quantity)
            ?: Requirement(b.quantity, b.componentName?.takeIf { it.isNotEmpty() }, b.location?.takeIf { it.isNotEmpty() })
    }
    return out
}

/**
 * Picking progress (V2_ORDERS_DELTA R4.3, same rule as the console): NOT_STARTED = no pick
 * entry for the order; DONE = every required SKU exact; EXTRA = a SKU picked that the order
 * lacks (wins); otherwise PARTIAL. [OrderProgress.doneSkus] counts SKUs picked exactly (Q46).
 */
fun progress(order: ShopeeOrderResponse, picks: List<PickItemEntryResponse>): OrderProgress {
    val bom = requirements(order)
    val mine = picks.filter { it.orderSn == order.orderSn }
    val skus = LinkedHashSet<String>().apply {
        addAll(bom.keys)
        mine.forEach { add(it.sku) }
    }
    val lines = skus.map { sku ->
        val req = bom[sku]
        val picked = mine.filter { it.sku == sku }.sumOf { it.qty }
        val name = req?.name
            ?: mine.firstOrNull { it.sku == sku && !it.itemName.isNullOrEmpty() }?.itemName
            ?: "Unknown item"
        SkuLine(sku, name, req?.location, req?.quantity ?: 0, picked)
    }
    val required = lines.filter { it.required > 0 }
    val done = required.count { it.picked == it.required }
    val state = when {
        lines.any { it.required == 0 } -> OrderState.EXTRA
        mine.isEmpty() -> OrderState.NOT_STARTED
        done == required.size -> OrderState.DONE
        else -> OrderState.PARTIAL
    }
    return OrderProgress(lines, done, required.size, state)
}

/** "Picking · 1/3 done": the state in words (C9) and the SKUs picked exactly (Q46). */
fun progressLabel(p: OrderProgress): String {
    val word = when (p.state) {
        OrderState.NOT_STARTED -> "Not started"
        OrderState.PARTIAL -> "Picking"
        OrderState.DONE -> "Picked"
        OrderState.EXTRA -> "Extra items"
    }
    return "$word · ${p.doneSkus}/${p.requiredSkus} done"
}

/**
 * The over-quantity warning after a pick, on the **resolved** SKU the server stored (spec §4.3
 * backlog: v1 compared the raw scan). Null when within the requirement or not part of the BOM.
 */
fun overQuantityWarning(order: ShopeeOrderResponse, picks: List<PickItemEntryResponse>, resolvedSku: String): String? {
    val required = requirements(order)[resolvedSku]?.quantity ?: return null
    val picked = picks.filter { it.orderSn == order.orderSn && it.sku == resolvedSku }.sumOf { it.qty }
    return if (picked > required) "Scan quantity ($picked) exceeds requirement ($required) for SKU: $resolvedSku" else null
}

/** v1 order search: SN, pickup code, BOM SKU or name, picked SKU or name (case-insensitive). */
fun matchesOrder(order: ShopeeOrderResponse, picks: List<PickItemEntryResponse>, query: String): Boolean {
    val q = query.trim().lowercase()
    if (q.isEmpty()) return true
    if (order.orderSn.lowercase().contains(q)) return true
    if (displayCode(order).lowercase().contains(q)) return true
    if (order.itemList.orEmpty().any { it.componentSku.lowercase().contains(q) || it.componentName.orEmpty().lowercase().contains(q) }) return true
    return picks.any { it.orderSn == order.orderSn && (it.sku.lowercase().contains(q) || it.itemName.orEmpty().lowercase().contains(q)) }
}

/** Default quantity in the v1 unassign dialog: the excess when over, else everything picked. */
fun unassignDefault(picked: Int, required: Int): Int = if (picked > required) picked - required else picked

/** Distinct non-empty locations that hold [sku] (case-insensitive), for the stock form. */
fun locationsFor(stocks: List<StockRow>, sku: String): List<String> =
    if (sku.isBlank()) emptyList()
    else stocks.filter { it.sku.equals(sku.trim(), true) && !it.location.isNullOrEmpty() }.mapNotNull { it.location }.distinct()
