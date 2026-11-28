package com.bakingholic.orderchecker.ops

import org.junit.Assert.assertEquals
import org.junit.Test

class MenuLayoutTest {
    @Test
    fun buttonsKeepTheirHeightWhenThereIsRoom() {
        assertEquals(72f, menuButtonHeight(availableDp = 470f, count = 5)) // Small_Phone
    }

    @Test
    fun buttonsShrinkToFitAShortScannerScreen() {
        // 320x569 dp with the button bar: about 390 dp between the top bar and the version line.
        val h = menuButtonHeight(availableDp = 390f, count = 5)
        assertEquals(65.2f, h, 0.01f)
        assertEquals(390f, 2 * 12f + 4 * 10f + 5 * h, 0.01f) // all five fit, Finder included
    }

    @Test
    fun belowTheTouchMinimumTheMenuScrollsInstead() {
        assertEquals(48f, menuButtonHeight(availableDp = 200f, count = 5))
    }
}
