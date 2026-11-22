package com.bakingholic.orderchecker.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppInfoTest {
    @Test
    fun clientVersionHeaderIsTheIntegerVersionCode() {
        assertEquals("7", AppInfo(7, "2.0.6").clientVersionHeader)
        assertEquals("v2.0.6 (7)", AppInfo(7, "2.0.6").label)
    }

    @Test
    fun serverMustOfferContractTwo() {
        assertTrue(AppInfo.supportsServer(1, 2))
        assertFalse(AppInfo.supportsServer(1, 1)) // a v0.5 backend has no /v2
    }
}
