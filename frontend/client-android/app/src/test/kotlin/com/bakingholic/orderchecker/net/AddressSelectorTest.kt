package com.bakingholic.orderchecker.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AddressSelectorTest {
    private val stage2 = ServerProfile(primary = "https://api.example.test", fallback = "http://192.168.1.50:8000")

    @Test
    fun stageOneHasOneAddressAndNeverFallsBack() {
        val s = AddressSelector().apply { update(ServerProfile(ServerProfile.STAGE1_PRIMARY)) }
        s.connectionFailed(ServerProfile.STAGE1_PRIMARY)
        assertEquals(listOf(ServerProfile.STAGE1_PRIMARY), s.order())
        assertFalse(s.onFallback())
    }

    @Test
    fun connectionFailureSwitchesAndAnswerSticks() {
        val s = AddressSelector().apply { update(stage2) }
        assertEquals(stage2.primary, s.order().first())
        s.connectionFailed(stage2.primary)
        assertEquals("http://192.168.1.50:8000", s.order().first())
        assertTrue(s.onFallback())
        s.answered("http://192.168.1.50:8000")
        assertEquals("http://192.168.1.50:8000", s.order().first()) // last answer wins
    }

    @Test
    fun primaryIsProbedOnlyOnFallbackAndAtMostEveryInterval() {
        var now = 0L
        val s = AddressSelector(probeIntervalMillis = 1_000, clock = { now }).apply { update(stage2) }
        assertFalse(s.primaryProbeDue())
        s.connectionFailed(stage2.primary)
        now = 5_000
        assertTrue(s.primaryProbeDue())
        now = 5_500
        assertFalse(s.primaryProbeDue())
        now = 6_100
        assertTrue(s.primaryProbeDue())
        s.answered(stage2.primary)
        assertFalse(s.onFallback())
    }

    @Test
    fun editingTheProfileKeepsAValidActiveAddress() {
        val s = AddressSelector().apply { update(stage2) }
        s.connectionFailed(stage2.primary)
        s.update(ServerProfile("http://10.0.0.9:8000"))
        assertEquals(listOf("http://10.0.0.9:8000"), s.order())
    }
}
