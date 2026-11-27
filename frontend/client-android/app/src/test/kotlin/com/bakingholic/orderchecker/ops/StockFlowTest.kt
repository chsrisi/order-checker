package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.StockCreate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Guided Stockkeeping (V2_UX §2.10) in both stock location modes. */
class StockFlowTest {
    private val mug = StockItem("SKU-0012", "Ceramic mug")
    private val single = listOf(StockRow(1, "SKU-0012", 40, "201"), StockRow(2, "SKU-0031", 12, "203"))
    private val multi = listOf(StockRow(1, "SKU-0012", 40, "A-01"), StockRow(2, "SKU-0012", 5, "B-02"))

    private fun at(action: StockAction, isSingle: Boolean, stocks: List<StockRow>, location: String) =
        StockFlow(action, isSingle).scanLocation(location, stocks)

    // ------------------------------------------------------------------ single mode (production)

    @Test
    fun singleCountAtTheRecordedRoom() {
        val flow = at(StockAction.COUNT, true, single, " 201 ").chooseItem(mug, single)
        assertEquals(StockStep.QUANTITY, flow.step)
        assertEquals(40, flow.recorded(single))
        val plan = flow.enterQty("36", single).plan(single)!!
        assertEquals(StockCreate.Mode.SET, plan.mode)
        assertEquals("201", plan.location)
        assertEquals(listOf(LocationChange("201", 40, 36)), plan.changes)
        assertFalse(plan.large)
        assertEquals("Count 36", plan.label)
    }

    @Test
    fun singleItemRecordedElsewhereNeverMovesSilently() {
        val flow = at(StockAction.RECEIVE, true, single, "203").chooseItem(mug, single)
        assertEquals("201", flow.mismatch)
        assertEquals(StockStep.ITEM, flow.step)
        assertNull(flow.plan(single))

        // K3 "Use 201": the receive goes to the recorded room.
        val used = flow.useRecorded(single).enterQty("12", single).plan(single)!!
        assertEquals("201", used.location)
        assertEquals(listOf(LocationChange("201", 40, 52)), used.changes)
        assertEquals("Receive 12 into 201", used.label)
    }

    @Test
    fun singleMoveItFirstThenBackToTheAction() {
        val flow = at(StockAction.COUNT, true, single, "203").chooseItem(mug, single)
        val move = flow.moveFirst(single)!!
        assertEquals(StockAction.MOVE, move.action)
        assertEquals(StockStep.CONFIRM, move.step)
        val plan = move.plan(single)!!
        assertEquals("201", plan.location)
        assertEquals("203", plan.moveTo)
        assertEquals(40, plan.qty)
        assertEquals("Move all 40 from 201 to 203", plan.label)

        val back = move.next()
        assertEquals(StockAction.COUNT, back.action)
        assertEquals(StockStep.QUANTITY, back.step)
        assertEquals("203", back.location)
        assertEquals(mug, back.item)
    }

    @Test
    fun singleMoveTakesEverythingWithoutAQuantity() {
        val flow = at(StockAction.MOVE, true, single, "201").chooseItem(mug, single)
        assertEquals(StockStep.DESTINATION, flow.step)
        assertEquals(40, flow.qty)
        val plan = flow.scanDestination("203", single).plan(single)!!
        assertEquals(listOf(LocationChange("201", 40, 0), LocationChange("203", 0, 40)), plan.changes)
    }

    @Test
    fun singleItemWithoutALocationTakesTheScannedOne() {
        val stocks = listOf(StockRow(1, "SKU-0012", 7, null))
        val plan = at(StockAction.COUNT, true, stocks, "305").chooseItem(mug, stocks).enterQty("9", stocks).plan(stocks)!!
        assertEquals("305", plan.location)
        assertEquals(listOf(LocationChange("305", 7, 9)), plan.changes)
    }

    // ------------------------------------------------------------------ multi mode

    @Test
    fun multiCountIsPerBin() {
        val flow = at(StockAction.COUNT, false, multi, "b-02").chooseItem(mug, multi)
        assertNull(flow.mismatch)
        assertEquals("B-02", flow.location) // the spelling on record
        assertEquals(5, flow.recorded(multi))
        val plan = flow.enterQty("6", multi).plan(multi)!!
        assertEquals(listOf(LocationChange("B-02", 5, 6)), plan.changes)
    }

    @Test
    fun multiReceiveIntoANewBin() {
        val plan = at(StockAction.RECEIVE, false, multi, "C-03").chooseItem(mug, multi).enterQty("10", multi).plan(multi)!!
        assertEquals("C-03", plan.location)
        assertEquals(listOf(LocationChange("C-03", 0, 10)), plan.changes)
    }

    @Test
    fun multiMoveChecksTheSourceBin() {
        val flow = at(StockAction.MOVE, false, multi, "B-02").chooseItem(mug, multi)
        assertEquals(StockStep.QUANTITY, flow.step)
        assertEquals("Only 5 at B-02.", flow.enterQty("6", multi).error)
        val dest = flow.enterQty("3", multi)
        assertEquals(StockStep.DESTINATION, dest.step)
        assertEquals("That is the same shelf.", dest.scanDestination("b-02", multi).error)
        val plan = dest.scanDestination("A-01", multi).plan(multi)!!
        assertEquals(listOf(LocationChange("B-02", 5, 2), LocationChange("A-01", 40, 43)), plan.changes)
        assertEquals("Move 3 from B-02 to A-01", plan.label)
    }

    @Test
    fun moveFromAnEmptyBinIsRefused() {
        assertEquals("Nothing of SKU-0012 at C-03.", at(StockAction.MOVE, false, multi, "C-03").chooseItem(mug, multi).error)
    }

    // ------------------------------------------------------------------ shared rules

    @Test
    fun quantitiesAreValidatedPerAction() {
        val count = at(StockAction.COUNT, true, single, "201").chooseItem(mug, single)
        assertEquals(StockStep.CONFIRM, count.enterQty("0", single).step) // a count of 0 is allowed
        assertEquals("Enter a number.", count.enterQty("x", single).error)
        val receive = at(StockAction.RECEIVE, true, single, "201").chooseItem(mug, single)
        assertEquals("Enter how many arrived.", receive.enterQty("0", single).error)
    }

    @Test
    fun largeChangeIsHalfTheRecordedQuantity() {
        assertTrue(isLargeChange(40, 4))
        assertTrue(isLargeChange(40, 61))
        assertFalse(isLargeChange(40, 20))
        assertFalse(isLargeChange(0, 36)) // a new bin
        val plan = at(StockAction.COUNT, true, single, "201").chooseItem(mug, single).enterQty("4", single).plan(single)!!
        assertTrue(plan.large)
    }

    @Test
    fun nextItemStaysAtTheSameShelf() {
        val next = at(StockAction.COUNT, true, single, "201").chooseItem(mug, single).enterQty("36", single).next()
        assertEquals(StockStep.ITEM, next.step)
        assertEquals("201", next.location)
        assertNull(next.item)
    }

    @Test
    fun backWalksTheStepsInReverse() {
        val confirm = at(StockAction.COUNT, true, single, "201").chooseItem(mug, single).enterQty("36", single)
        assertEquals(StockStep.QUANTITY, confirm.back().step)
        assertEquals(StockStep.ITEM, confirm.back().back().step)
        assertEquals(StockStep.LOCATION, confirm.back().back().back().step)
    }

    @Test
    fun anEmptyScanIsAnError() {
        assertNotNull(StockFlow(StockAction.COUNT, true).scanLocation("  ", single).error)
    }

    // ------------------------------------------------------------------ task mode (T9.4)

    @Test
    fun taskModeLocksTheScansAndHidesTheQuantity() {
        val lock = StockLock(sku = "SKU-0012", location = "201")
        val start = StockFlow(StockAction.COUNT, true, lock = lock)
        assertEquals("This task is for 201, not 203.", start.scanLocation("203", single).error)
        val atShelf = start.scanLocation("201", single)
        assertEquals("This task is for SKU-0012, not SKU-0031.", atShelf.chooseItem(StockItem("SKU-0031", null), single).error)
        val counting = atShelf.chooseItem(mug, single)
        assertTrue(counting.blind)
        assertNull(counting.recorded(single))
    }

    @Test
    fun singleModeTaskWithoutALocationUsesTheRecordedOne() {
        val start = StockFlow(StockAction.COUNT, true, lock = StockLock(sku = "SKU-0012", location = null))
        assertEquals("This task is for 201, not 203.", start.scanLocation("203", single).error)
        assertEquals(StockStep.ITEM, start.scanLocation("201", single).step)
    }
}
