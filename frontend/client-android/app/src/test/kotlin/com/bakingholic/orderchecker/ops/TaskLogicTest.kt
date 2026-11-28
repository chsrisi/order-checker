package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.ShopeeOrderItemBOMResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.api.model.TaskLineResponse
import com.bakingholic.orderchecker.api.model.TaskResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The Tasks list and pick-task rules of T9.4 (V2_UX §2.9). */
class TaskLogicTest {
    private fun task(
        id: Int,
        created: String,
        status: TaskResponse.Status = TaskResponse.Status.OPEN,
        type: TaskResponse.Type = TaskResponse.Type.PICK,
        lines: List<TaskLineResponse> = emptyList(),
        reference: String? = null,
    ) = TaskResponse(
        assignedTo = "op", createdAt = created, createdBy = "boss", id = id, inProgress = false,
        lines = lines, status = status, type = type, reference = reference,
    )

    private fun leaf(sku: String, qty: Int, picked: Int) =
        TaskLineResponse(id = qty, kind = TaskLineResponse.Kind.LEAF, sku = sku, qty = qty, picked = picked)

    private fun order(sn: String, shipBy: String) = ShopeeOrderResponse(
        done = false, orderSn = sn, shipBy = shipBy, splitUp = false, status = "READY_TO_SHIP",
        itemList = listOf(ShopeeOrderItemBOMResponse(componentSku = "A", quantity = 2)),
    )

    @Test
    fun manualTasksOldestFirstThenClaimedOrdersByShipBy() {
        val entries = taskEntries(
            tasks = listOf(task(2, "2026-11-27T10:00:00Z"), task(1, "2026-11-27T09:00:00Z", TaskResponse.Status.BLOCKED)),
            orders = listOf(order("B", "2026-11-29T00:00:00Z"), order("A", "2026-11-28T00:00:00Z")),
            picks = emptyList(),
        )
        assertEquals(listOf("t1", "t2", "oA", "oB"), entries.map { if (it is TaskEntry.Manual) "t${it.task.id}" else "o${(it as TaskEntry.Order).order.orderSn}" })
    }

    @Test
    fun aPickedOrderLeavesTheListAndBlockedTasksAreNotCounted() {
        val picks = listOf(OrderPick("A", "A", null, 2))
        val entries = taskEntries(
            tasks = listOf(task(1, "t1"), task(2, "t2", TaskResponse.Status.BLOCKED), task(3, "t3", TaskResponse.Status.DONE)),
            orders = listOf(order("A", "s1"), order("B", "s2")),
            picks = picks,
        )
        assertEquals(4, entries.size + 1) // done task 3 and picked order A are gone; t1, t2, oB stay
        assertEquals(2, openTaskCount(entries)) // t1 and order B
    }

    @Test
    fun pickTaskProgressAndTheOverPickWarning() {
        val t = task(1, "t", lines = listOf(leaf("A", 2, 2), leaf("B", 3, 1)), reference = "Toko Sinar")
        assertEquals(1, t.pickedExactly())
        assertEquals("Pick · Toko Sinar · 1/2 done", describeTask(t))
        assertEquals(LineState.PARTIAL, lineState(t.leaves()[1]))
        assertNull(taskPickWarning(t, "B", 3))
        assertEquals("Scan quantity (4) exceeds requirement (3) for SKU: B", taskPickWarning(t, "B", 4))
    }

    @Test
    fun aCountSaysWhatAndWhere() {
        val count = task(
            1, "t", type = TaskResponse.Type.COUNT,
            lines = listOf(TaskLineResponse(id = 1, kind = TaskLineResponse.Kind.COUNT, sku = "A01_001", itemName = "Flour", location = "201")),
        )
        assertEquals("Count Flour · at 201", describeTask(count))
    }
}
