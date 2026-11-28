package com.bakingholic.orderchecker.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LoginFormTest {
    private val known = listOf("bob", "alice") // bob logged in last

    @Test
    fun startsOnThePickerWithTheLastWorker() {
        assertEquals(LoginStep.PICK, LoginForm().step)
        assertEquals("bob", LoginForm().worker(known))
        assertNull(LoginForm().credentials(known))
    }

    @Test
    fun loginAsksForThePasswordOfThePickedWorker() {
        val form = LoginForm().pick("alice").askPassword(known)
        assertEquals(LoginStep.PASSWORD, form.step)
        assertNull(form.credentials(known))
        assertEquals("alice" to "pw", form.copy(password = "pw").credentials(known))
    }

    @Test
    fun anAdminPreselectionOpensThatWorkersPasswordStep() {
        // T8.7: also for a worker who never logged in on this device.
        val form = LoginForm().pick("bob").copy(password = "typed").preselect("eko")
        assertEquals(LoginStep.PASSWORD, form.step)
        assertEquals("eko", form.worker(known))
        assertNull(form.credentials(known)) // the password typed for bob is gone
        assertEquals("eko" to "pw", form.copy(password = "pw").credentials(known))
    }

    @Test
    fun withoutAKnownWorkerLoginStaysOnThePicker() {
        assertEquals(LoginForm(), LoginForm().askPassword(emptyList()))
    }

    @Test
    fun changingTheWorkerDropsTheTypedPassword() {
        val form = LoginForm().askPassword(known).copy(password = "bobs").pick("alice")
        assertEquals(LoginStep.PASSWORD, form.step)
        assertNull(form.credentials(known))
    }

    @Test
    fun theWorkerIsFixedOnceThePasswordIsAsked() {
        val form = LoginForm().askPassword(known).copy(password = "pw")
        assertEquals("bob" to "pw", form.credentials(listOf("carol", "bob")))
    }

    @Test
    fun manualInputIgnoresThePicker() {
        val form = LoginForm().pick("alice").manual().copy(password = "pw")
        assertNull(form.credentials(known))
        assertEquals("carol" to "pw", form.copy(username = " carol ").credentials(known))
    }

    @Test
    fun backReturnsToThePickerWithoutThePassword() {
        val form = LoginForm().manual().copy(username = "carol", password = "pw").back()
        assertEquals(LoginStep.PICK, form.step)
        assertEquals("", form.password)
    }
}
