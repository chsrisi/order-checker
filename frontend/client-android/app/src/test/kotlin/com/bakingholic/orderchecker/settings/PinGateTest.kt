package com.bakingholic.orderchecker.settings

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PinGateTest {
    @Test
    fun acceptsOnlyTheConfiguredPin() {
        val gate = PinGate("4821")
        assertTrue(gate.accepts("4821"))
        assertTrue(gate.accepts(" 4821 "))
        assertFalse(gate.accepts("4822"))
        assertFalse(gate.accepts(""))
    }

    @Test
    fun aBuildWithoutPinCannotUnlock() {
        val gate = PinGate("")
        assertFalse(gate.enabled)
        assertFalse(gate.accepts(""))
    }
}
