package com.bakingholic.orderchecker.ws

import kotlin.random.Random

/**
 * Reconnect delays without a retry limit (unlike v1, which gave up after ~10 s): 1 s, doubling
 * to a 30 s cap, each with ±20 % jitter so two scanners do not reconnect in lockstep.
 */
class Backoff(
    private val baseMillis: Long = 1_000,
    private val capMillis: Long = 30_000,
    private val jitter: Double = 0.2,
    private val random: Random = Random.Default,
) {
    private var attempt = 0

    fun next(): Long {
        val raw = (baseMillis shl attempt.coerceAtMost(15)).coerceAtMost(capMillis)
        attempt++
        val spread = (raw * jitter).toLong()
        return (raw + random.nextLong(-spread, spread + 1)).coerceAtLeast(0)
    }

    fun reset() {
        attempt = 0
    }
}
