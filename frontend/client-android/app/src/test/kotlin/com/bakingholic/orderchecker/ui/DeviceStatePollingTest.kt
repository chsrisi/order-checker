package com.bakingholic.orderchecker.ui

import com.bakingholic.orderchecker.auth.LoginWait
import com.bakingholic.orderchecker.device.DeviceState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** W5: the state poll runs only on an idle login screen in the foreground. */
class DeviceStatePollingTest {
    @Test
    fun pollsOnlyOnAnIdleLoginScreenInTheForeground() {
        assertTrue(pollsDeviceState(Screen.Login(), foreground = true))
        assertTrue(pollsDeviceState(Screen.Login(error = "Session ended. Please log in again."), foreground = true))
        assertFalse(pollsDeviceState(Screen.Login(), foreground = false)) // background
        assertFalse(pollsDeviceState(Screen.Home, foreground = true)) // after login
        assertFalse(pollsDeviceState(Screen.Login(busy = true), foreground = true)) // password login running
        assertFalse(pollsDeviceState(Screen.Login(waiting = LoginWait("eko", "42", 0)), foreground = true))
        assertFalse(pollsDeviceState(Screen.Starting, foreground = true))
        assertFalse(pollsDeviceState(Screen.UpdateRequired(null), foreground = true))
    }

    private val ended = Screen.Login(error = "Session ended. Please log in again.")

    @Test
    fun aPreselectionReplacesSessionEndedWithTheAdminsChoice() {
        val next = loginAfter(ended, DeviceState.Preselect("eko", "Switched by the admin to eko."))
        assertNull(next.error)
        assertEquals("eko", next.preselect)
        assertEquals("Switched by the admin to eko. The admin chose eko. Enter the password.", next.notice)
    }

    @Test
    fun theLogoutReasonGoesUnderSessionEnded() {
        val next = loginAfter(ended, DeviceState.Idle("Logged out by the admin."))
        assertEquals("Session ended. Please log in again.", next.error)
        assertEquals("Logged out by the admin.", next.notice)
    }

    @Test
    fun revokedAndClockOffAreShown() {
        assertEquals("This device was revoked by the admin.", loginAfter(ended, DeviceState.Revoked).error)
        assertEquals(
            "The device clock is wrong: the admin can't switch workers on it.",
            loginAfter(Screen.Login(), DeviceState.ClockOff).notice,
        )
    }
}
