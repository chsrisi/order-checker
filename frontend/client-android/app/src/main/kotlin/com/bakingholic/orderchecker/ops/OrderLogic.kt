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

fun progress(order: ShopeeOrderResponse, picks: List<PickItemEntryResponse>): OrderProgress {
    val bom = order.itemList.orEmpty()
    val mine = picks.filter { it.orderSn == order.orderSn }
    val skus = LinkedHashSet<String>().apply {
        bom.forEach { add(bomSku(it.componentSku)) }
        mine.forEach { add(it.sku) }
    }
    val lines = skus.map { sku ->
        val req = bom.firstOrNull { bomSku(it.componentSku) == sku }
        val picked = mine.filter { it.sku == sku }.sumOf { it.qty }
        val name = req?.componentName?.takeIf { it.isNotEmpty() }
            ?: mine.firstOrNull { it.sku == sku && !it.itemName.isNullOrEmpty() }?.itemName
            ?: "Unknown item"
        SkuLine(sku, name, req?.location?.takeIf { it.isNotEmpty() }, req?.quantity ?: 0, picked)
    }
    val done = lines.count { it.required == it.picked }
    val state = when {
        lines.any { it.required == 0 } -> OrderState.EXTRA
        done == 0 -> OrderState.NOT_STARTED
        done < bom.size -> OrderState.PARTIAL
        else -> OrderState.DONE
    }
    return OrderProgress(lines, done, bom.size, state)
}

/**
 * The over-quantity warning after a pick, on the **resolved** SKU the server stored (spec §4.3
 * backlog: v1 compared the raw scan). Null when within the requirement or not part of the BOM.
 */
fun overQuantityWarning(order: ShopeeOrderResponse, picks: List<PickItemEntryResponse>, resolvedSku: String): String? {
    val required = order.itemList.orEmpty().firstOrNull { bomSku(it.componentSku) == resolvedSku }?.quantity ?: return null
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
