package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.PickItemEntryResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderInfoResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderItemBOMResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OrderLogicTest {
    private val order = ShopeeOrderResponse(
        orderSn = "251120ABC",
        shipBy = "2025-11-21T00:00:00",
        status = "READY_TO_SHIP",
        info = listOf(ShopeeOrderInfoResponse(id = 1, pickupCode = "PK-77")),
        itemList = listOf(
            ShopeeOrderItemBOMResponse(componentSku = "CAKE-1", quantity = 2, componentName = "Choco cake", location = "A1"),
            ShopeeOrderItemBOMResponse(componentSku = "", quantity = 1),
        ),
    )
    private var nextId = 1

    private fun pick(sku: String, qty: Int, orderSn: String? = order.orderSn, name: String? = null) =
        PickItemEntryResponse(id = nextId++, ownerUser = "ana", qty = qty, sku = sku, timestamp = "t", itemName = name, orderSn = orderSn)

    @Test
    fun progressFollowsTheBomAndThePicks() {
        assertEquals(OrderState.NOT_STARTED, progress(order, emptyList()).state)
        val partial = progress(order, listOf(pick("CAKE-1", 1)))
        assertEquals(OrderState.NOT_STARTED, partial.state) // no SKU complete yet
        assertEquals(LineState.PARTIAL, partial.lines.first { it.sku == "CAKE-1" }.state)
        val one = progress(order, listOf(pick("CAKE-1", 2)))
        assertEquals(OrderState.PARTIAL, one.state)
        assertEquals(1, one.doneSkus)
        // An empty component SKU is "unknown", as in v1.
        val done = progress(order, listOf(pick("CAKE-1", 2), pick(UNKNOWN_SKU, 1)))
        assertEquals(OrderState.DONE, done.state)
        // A SKU outside the BOM marks the order as having extras; picks of other orders don't count.
        val extra = progress(order, listOf(pick("OTHER", 1, name = "Candle"), pick("CAKE-1", 5, orderSn = "X")))
        assertEquals(OrderState.EXTRA, extra.state)
        assertEquals("Candle", extra.lines.first { it.sku == "OTHER" }.name)
        assertEquals(0, extra.lines.first { it.sku == "CAKE-1" }.picked)
    }

    @Test
    fun overQuantityWarningUsesTheResolvedSku() {
        assertNull(overQuantityWarning(order, listOf(pick("CAKE-1", 2)), "CAKE-1"))
        val warning = overQuantityWarning(order, listOf(pick("CAKE-1", 2), pick("CAKE-1", 1)), "CAKE-1")
        assertEquals("Scan quantity (3) exceeds requirement (2) for SKU: CAKE-1", warning)
        assertNull(overQuantityWarning(order, listOf(pick("OTHER", 9)), "OTHER")) // not in the BOM
    }

    @Test
    fun orderSearchMatchesCodesSkusAndNames() {
        val picks = listOf(pick("CANDLE-9", 1, name = "Birthday candle"))
        assertTrue(matchesOrder(order, picks, ""))
        assertTrue(matchesOrder(order, picks, "pk-77"))
        assertTrue(matchesOrder(order, picks, "251120"))
        assertTrue(matchesOrder(order, picks, "choco"))
        assertTrue(matchesOrder(order, picks, "birthday"))
        assertFalse(matchesOrder(order, picks, "vanilla"))
        assertEquals("PK-77", displayCode(order))
    }

    @Test
    fun orderLabelsMustStartWithADate() {
        assertTrue(ORDER_SN_PATTERN.matches("251120ABCDEF"))
        assertFalse(ORDER_SN_PATTERN.matches("SPX123"))
    }

    @Test
    fun unassignDefaultsToTheExcess() {
        assertEquals(1, unassignDefault(picked = 3, required = 2))
        assertEquals(2, unassignDefault(picked = 2, required = 2))
    }

    @Test
    fun stockLocationsForASku() {
        val stocks = listOf(
            StockRow(1, "CAKE-1", 3, "A1"),
            StockRow(2, "cake-1", 1, "B2"),
            StockRow(3, "CAKE-1", 0, null),
            StockRow(4, "X", 1, "C3"),
        )
        assertEquals(listOf("A1", "B2"), locationsFor(stocks, " CAKE-1 "))
        assertEquals(emptyList<String>(), locationsFor(stocks, ""))
    }
}
