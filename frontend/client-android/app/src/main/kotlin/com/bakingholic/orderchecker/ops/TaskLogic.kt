package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.api.model.TaskLineResponse
import com.bakingholic.orderchecker.api.model.TaskResponse

/**
 * The worker's Tasks list (T9.4, V2_UX §2.9): tasks from the admin plus claimed orders that are
 * not *Picked* yet. Order-tasks are derived here with the Picking rule ([progress]), never stored
 * (V2_TASKS_DELTA R1.3), so they follow the order and pick frames the app already has.
 */
sealed interface TaskEntry {
    val blocked: Boolean

    data class Manual(val task: TaskResponse) : TaskEntry {
        override val blocked get() = task.status == TaskResponse.Status.BLOCKED
    }

    data class Order(val order: ShopeeOrderResponse, val progress: OrderProgress) : TaskEntry {
        override val blocked get() = false
    }
}

/**
 * Manual tasks first, oldest first (T11), then the claimed orders by ship-by (the most urgent
 * first). Done and cancelled tasks are not sent to workers; a *Picked* order leaves the list.
 */
fun taskEntries(tasks: List<TaskResponse>, orders: List<ShopeeOrderResponse>, picks: List<OrderPick>): List<TaskEntry> {
    val manual = tasks
        .filter { it.status == TaskResponse.Status.OPEN || it.status == TaskResponse.Status.BLOCKED }
        .sortedWith(compareBy({ it.createdAt }, { it.id }))
        .map { TaskEntry.Manual(it) }
    val claimed = orders
        .map { TaskEntry.Order(it, progress(it, picks)) }
        .filter { it.progress.state != OrderState.DONE }
        .sortedBy { it.order.shipBy }
    return manual + claimed
}

/** The number on the Home button: what can be worked on now (blocked tasks wait for the admin). */
fun openTaskCount(entries: List<TaskEntry>): Int = entries.count { !it.blocked }

fun TaskResponse.leaves(): List<TaskLineResponse> = lines.filter { it.kind == TaskLineResponse.Kind.LEAF }

fun TaskResponse.countLine(): TaskLineResponse? = lines.firstOrNull { it.kind == TaskLineResponse.Kind.COUNT }

/** SKUs picked exactly, of the task's lines ("2/5 done", as for orders). */
fun TaskResponse.pickedExactly(): Int = leaves().count { (it.picked ?: 0) == (it.qty ?: 0) }

/** A pick task line in the Picking colours. */
fun lineState(line: TaskLineResponse): LineState {
    val picked = line.picked ?: 0
    val required = line.qty ?: 0
    return when {
        picked == 0 -> LineState.NONE
        picked < required -> LineState.PARTIAL
        picked == required -> LineState.DONE
        else -> LineState.OVER
    }
}

/** One line saying what a task is, for the list. */
fun describeTask(task: TaskResponse): String = when (task.type) {
    TaskResponse.Type.COUNT -> {
        val line = task.countLine()
        val where = line?.location ?: task.currentLocation
        listOfNotNull("Count ${line?.itemName ?: line?.sku ?: ""}".trim(), where?.let { "at $it" }).joinToString(" · ")
    }
    TaskResponse.Type.PICK -> listOfNotNull("Pick", task.reference, "${task.pickedExactly()}/${task.leaves().size} done").joinToString(" · ")
}

/** The over-quantity warning after a task pick (same rule and words as for an order, Q63). */
fun taskPickWarning(task: TaskResponse, resolvedSku: String, total: Int): String? {
    val required = task.leaves().firstOrNull { it.sku == resolvedSku }?.qty ?: return null
    return if (total > required) "Scan quantity ($total) exceeds requirement ($required) for SKU: $resolvedSku" else null
}

/** Quick reasons for *Can't finish* (UX-T7); the worker may also type one. */
val CANT_FINISH_REASONS = listOf("Not enough stock", "Item not found", "Damaged")
