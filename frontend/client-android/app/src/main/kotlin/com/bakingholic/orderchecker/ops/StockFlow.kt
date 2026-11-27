package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.StockCreate
import kotlin.math.abs

/**
 * Guided Stockkeeping (V2_UX §2.10, V2_STOCK_DELTA R1.2): every action is
 * location → item → quantity → (destination) → confirm. Pure, so the rules are unit-tested; the
 * screen only renders a [StockFlow] and feeds it scans.
 *
 * Locations are compared trimmed and case-insensitively, but sent with the spelling already on
 * record, so a scan never creates a second bin that differs only in case. No location format is
 * assumed (S3: today a location is a room number such as `203`, and that will change).
 */
enum class StockAction(val title: String, val hint: String) {
    RECEIVE("Receive", "Put new stock on a shelf"),
    COUNT("Count", "Say how many are on a shelf"),
    MOVE("Move", "Take stock from one shelf to another"),
}

enum class StockStep { LOCATION, ITEM, QUANTITY, DESTINATION, CONFIRM }

data class StockItem(val sku: String, val name: String?)

/**
 * A count task's constraints (shared with T9.4): the scans must match, and the recorded quantity
 * is hidden (blind, V2_TASKS_DELTA T6). [location] is null for a `single` mode task (P-29): the
 * item's recorded location is then the one to scan.
 */
data class StockLock(val sku: String, val location: String?, val blind: Boolean = true)

data class LocationChange(val location: String?, val before: Int, val after: Int)

/** What the confirm step shows and what is sent to `POST /v2/stocks/update`. */
data class StockPlan(
    val sku: String,
    val qty: Int,
    val mode: StockCreate.Mode,
    val location: String?,
    val moveTo: String?,
    val changes: List<LocationChange>,
    val large: Boolean,
    val label: String,
)

fun sameLocation(a: String?, b: String?): Boolean =
    a != null && b != null && a.trim().equals(b.trim(), ignoreCase = true)

private fun rowsOf(stocks: List<StockRow>, sku: String) = stocks.filter { it.sku.equals(sku, ignoreCase = true) }

/** Quantity of [sku] at [location] (`multi`), or the item's total (`single`: one row). */
fun recordedQty(stocks: List<StockRow>, sku: String, location: String?, single: Boolean): Int {
    val rows = rowsOf(stocks, sku)
    return if (single) rows.sumOf { it.stock } else rows.filter { sameLocation(it.location, location) }.sumOf { it.stock }
}

/** The item's locations on record, in location order. */
fun recordedLocations(stocks: List<StockRow>, sku: String): List<String> =
    rowsOf(stocks, sku).mapNotNull { it.location?.takeIf(String::isNotBlank) }.distinct().sorted()

/** The spelling on record for [raw], or [raw] trimmed. */
fun canonicalLocation(stocks: List<StockRow>, raw: String): String {
    val trimmed = raw.trim()
    return stocks.firstNotNullOfOrNull { row -> row.location?.takeIf { sameLocation(it, trimmed) } } ?: trimmed
}

/** A count that changes the recorded quantity by more than half (K4). */
fun isLargeChange(before: Int, after: Int): Boolean = before > 0 && abs(after - before) * 2 > before

data class StockFlow(
    val action: StockAction,
    val single: Boolean,
    val lock: StockLock? = null,
    val step: StockStep = StockStep.LOCATION,
    val location: String? = null,
    val item: StockItem? = null,
    val qty: Int? = null,
    val destination: String? = null,
    /** `single` mode: the item is recorded at this other location; the worker chooses (K3). */
    val mismatch: String? = null,
    /** After "Move it first": the action to return to once the move is done. */
    val resume: StockFlow? = null,
    val error: String? = null,
) {
    val blind: Boolean get() = lock?.blind == true

    /** Recorded quantity for the item step; null when hidden (task mode) or not known yet. */
    fun recorded(stocks: List<StockRow>): Int? =
        item?.takeUnless { blind }?.let { recordedQty(stocks, it.sku, location, single) }

    private fun fail(message: String) = copy(error = message)

    fun scanLocation(raw: String, stocks: List<StockRow>): StockFlow {
        val scanned = raw.trim()
        if (scanned.isEmpty()) return fail("Scan the shelf label.")
        val expected = lock?.location ?: lock?.let { recordedLocations(stocks, it.sku).firstOrNull() }
        if (lock != null && expected != null && !sameLocation(scanned, expected)) {
            return fail("This task is for $expected, not $scanned.")
        }
        return copy(step = StockStep.ITEM, location = canonicalLocation(stocks, scanned), error = null)
    }

    fun chooseItem(found: StockItem, stocks: List<StockRow>): StockFlow {
        if (lock != null && !found.sku.equals(lock.sku, ignoreCase = true)) {
            return fail("This task is for ${lock.sku}, not ${found.sku}.")
        }
        val withItem = copy(item = found, error = null, mismatch = null)
        if (single) {
            val recorded = recordedLocations(stocks, found.sku)
            if (recorded.isNotEmpty() && recorded.none { sameLocation(it, location) }) {
                return withItem.copy(mismatch = recorded.first())
            }
        }
        return withItem.afterItem(stocks)
    }

    /** K3 "Use 201": carry on at the location on record. */
    fun useRecorded(stocks: List<StockRow>): StockFlow {
        val other = mismatch ?: return this
        return copy(location = other, mismatch = null).afterItem(stocks)
    }

    /** K3 "Move it to 203 first": a Move from the recorded location, then back to this action. */
    fun moveFirst(stocks: List<StockRow>): StockFlow? {
        val other = mismatch ?: return null
        val found = item ?: return null
        val here = location ?: return null
        return StockFlow(
            action = StockAction.MOVE,
            single = single,
            step = StockStep.CONFIRM,
            location = other,
            item = found,
            qty = recordedQty(stocks, found.sku, other, single),
            destination = here,
            resume = copy(mismatch = null, step = StockStep.QUANTITY, error = null),
        )
    }

    private fun afterItem(stocks: List<StockRow>): StockFlow {
        val found = item ?: return this
        if (action == StockAction.MOVE) {
            val available = recordedQty(stocks, found.sku, location, single)
            if (available <= 0) return fail("Nothing of ${found.sku} at $location.")
            // single mode moves everything (SYSTEM_REFERENCE §7.6): no quantity to ask for.
            if (single) return copy(qty = available, step = StockStep.DESTINATION)
        }
        return copy(step = StockStep.QUANTITY)
    }

    fun enterQty(raw: String, stocks: List<StockRow>): StockFlow {
        val n = raw.trim().toIntOrNull() ?: return fail("Enter a number.")
        val found = item ?: return this
        when (action) {
            StockAction.COUNT -> if (n < 0) return fail("A count can't be negative.")
            StockAction.RECEIVE -> if (n <= 0) return fail("Enter how many arrived.")
            StockAction.MOVE -> {
                if (n <= 0) return fail("Enter how many to move.")
                val available = recordedQty(stocks, found.sku, location, single)
                if (n > available) return fail("Only $available at $location.")
            }
        }
        val next = if (action == StockAction.MOVE) StockStep.DESTINATION else StockStep.CONFIRM
        return copy(qty = n, step = next, error = null)
    }

    fun scanDestination(raw: String, stocks: List<StockRow>): StockFlow {
        val scanned = raw.trim()
        if (scanned.isEmpty()) return fail("Scan the destination shelf.")
        if (sameLocation(scanned, location)) return fail("That is the same shelf.")
        return copy(destination = canonicalLocation(stocks, scanned), step = StockStep.CONFIRM, error = null)
    }

    fun plan(stocks: List<StockRow>): StockPlan? {
        val found = item ?: return null
        val n = qty ?: return null
        val here = location
        return when (action) {
            StockAction.RECEIVE -> {
                val before = recordedQty(stocks, found.sku, here, single)
                StockPlan(found.sku, n, StockCreate.Mode.ADD, here, null, listOf(LocationChange(here, before, before + n)), false, "Receive $n into $here")
            }
            StockAction.COUNT -> {
                val before = recordedQty(stocks, found.sku, here, single)
                StockPlan(found.sku, n, StockCreate.Mode.SET, here, null, listOf(LocationChange(here, before, n)), isLargeChange(before, n), "Count $n")
            }
            StockAction.MOVE -> {
                val dest = destination ?: return null
                val from = recordedQty(stocks, found.sku, here, single)
                val to = if (single) 0 else recordedQty(stocks, found.sku, dest, single)
                val label = if (single) "Move all $n from $here to $dest" else "Move $n from $here to $dest"
                StockPlan(
                    found.sku, n, StockCreate.Mode.ADD, here, dest,
                    listOf(LocationChange(here, from, from - n), LocationChange(dest, to, to + n)), false, label,
                )
            }
        }
    }

    /** After a successful change: back to the original action, or the next item at this shelf (K2). */
    fun next(): StockFlow =
        resume ?: copy(step = StockStep.ITEM, item = null, qty = null, destination = null, mismatch = null, error = null)

    fun back(): StockFlow = when (step) {
        StockStep.LOCATION -> this
        StockStep.ITEM -> copy(step = StockStep.LOCATION, item = null, mismatch = null, error = null)
        StockStep.QUANTITY -> copy(step = StockStep.ITEM, qty = null, error = null)
        StockStep.DESTINATION ->
            if (single && action == StockAction.MOVE) copy(step = StockStep.ITEM, qty = null, error = null)
            else copy(step = StockStep.QUANTITY, destination = null, error = null)
        StockStep.CONFIRM -> when {
            resume != null -> resume.copy(step = StockStep.ITEM, mismatch = null)
            action == StockAction.MOVE -> copy(step = StockStep.DESTINATION, destination = null, error = null)
            else -> copy(step = StockStep.QUANTITY, error = null)
        }
    }
}
