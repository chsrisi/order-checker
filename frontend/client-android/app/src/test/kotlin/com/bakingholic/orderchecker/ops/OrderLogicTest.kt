package com.bakingholic.orderchecker.ops

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
        info = listOf(ShopeeOrderInfoResponse(id = 1, pickupCode = "PK-77", trackingNumber = "SPXID77")),
        itemList = listOf(
            ShopeeOrderItemBOMResponse(componentSku = "CAKE-1", quantity = 2, componentName = "Choco cake", location = "A1"),
            ShopeeOrderItemBOMResponse(componentSku = "", quantity = 1),
        ),
    )

    private fun pick(sku: String, qty: Int, orderSn: String = order.orderSn, name: String? = null) =
        OrderPick(orderSn, sku, name, qty)

    @Test
    fun progressFollowsTheBomAndThePicks() {
        assertEquals(OrderState.NOT_STARTED, progress(order, emptyList()).state)
        val partial = progress(order, listOf(pick("CAKE-1", 1)))
        assertEquals(OrderState.PARTIAL, partial.state) // R4.3: any pick entry means Picking
        assertEquals(0, partial.doneSkus)
        assertEquals(OrderState.NOT_STARTED, progress(order, listOf(pick("CAKE-1", 2, orderSn = "X"))).state)
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
    fun bomLinesSharingASkuAreOneRequirement() {
        // V2_ORDERS_DELTA F2: the server sums per (sku, name, location), so one SKU can come on
        // two lines; before, the order could never reach DONE.
        val twice = order.copy(
            itemList = listOf(
                ShopeeOrderItemBOMResponse(componentSku = "MUG", quantity = 1, componentName = "Mug (listing 1)"),
                ShopeeOrderItemBOMResponse(componentSku = "MUG", quantity = 2, componentName = "Mug (listing 2)"),
            ),
        )
        val p = progress(twice, listOf(pick("MUG", 3)))
        assertEquals(OrderState.DONE, p.state)
        assertEquals(1, p.requiredSkus)
        assertEquals(3, p.lines.single().required)
        assertNull(pickWarning(twice, "MUG", 3))
        assertEquals("Picking · 0/1 done", progressLabel(progress(twice, listOf(pick("MUG", 1)))))
    }

    @Test
    fun pickWarnsAboutTooManyAndAboutExtraSkus() {
        assertNull(pickWarning(order, "CAKE-1", 2))
        assertEquals("Scan quantity (3) exceeds requirement (2) for SKU: CAKE-1", pickWarning(order, "CAKE-1", 3))
        assertTrue(pickWarning(order, "OTHER", 1)!!.startsWith("OTHER is not part of this order"))
    }

    @Test
    fun pickedOrdersGoLastAndComeBack() {
        val other = order.copy(orderSn = "251120XYZ")
        val all = listOf(pick("CAKE-1", 2), pick(UNKNOWN_SKU, 1))
        assertEquals(listOf(other) to listOf(order), splitPicked(listOf(order, other), all))
        assertEquals(listOf(order, other), splitPicked(listOf(order, other), all.dropLast(1)).first)
        // Extra items still need work: not sunk.
        assertEquals(listOf(order, other), splitPicked(listOf(order, other), all + pick("OTHER", 1)).first)
    }

    @Test
    fun quantitiesAreWholeNumbersInRange() {
        assertEquals(3, validQty(" 3 ", 3))
        listOf("", "0", "4", "-1", "x", "99999999999").forEach { assertNull(it, validQty(it, 3)) }
        assertNull(validQty("99999999999"))
    }

    @Test
    fun orderSearchMatchesCodesSkusAndNames() {
        val picks = listOf(pick("CANDLE-9", 1, name = "Birthday candle"))
        assertTrue(matchesOrder(order, picks, ""))
        assertTrue(matchesOrder(order, picks, "pk-77"))
        assertTrue(matchesOrder(order, picks, "spxid77"))
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
}
