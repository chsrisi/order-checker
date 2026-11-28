package com.bakingholic.orderchecker.scan

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScanInputTest {
    @Test
    fun gateTrimsAndIgnoresBlanks() {
        val gate = ScanGate(clock = { 0L })
        assertNull(gate.accept(""))
        assertNull(gate.accept("   "))
        assertEquals("ABC-1", gate.accept("  ABC-1 "))
    }

    @Test
    fun gateDropsWedgeDoubleFireButNotARealRescan() {
        var now = 1_000L
        val gate = ScanGate(dedupeWindowMs = 300, clock = { now })
        assertEquals("SKU1", gate.accept("SKU1"))
        now += 100
        assertNull(gate.accept("SKU1")) // same value within 300 ms: a double fire
        now += 299
        assertEquals("SKU1", gate.accept("SKU1")) // 399 ms after the first: a real rescan
        now += 10
        assertEquals("SKU2", gate.accept("SKU2")) // another value is never dropped
        assertEquals("SKU1", gate.accept("SKU1"))
    }

    @Test
    fun suffixKeysFollowTheSetting() {
        assertEquals(ScanEnding.ENTER, suffixEnding(KeyEvent.KEYCODE_ENTER, ScanSuffix.ENTER))
        assertEquals(ScanEnding.ENTER, suffixEnding(KeyEvent.KEYCODE_NUMPAD_ENTER, ScanSuffix.ENTER))
        assertNull(suffixEnding(KeyEvent.KEYCODE_TAB, ScanSuffix.ENTER))
        assertEquals(ScanEnding.TAB, suffixEnding(KeyEvent.KEYCODE_TAB, ScanSuffix.TAB))
        assertNull(suffixEnding(KeyEvent.KEYCODE_ENTER, ScanSuffix.TAB))
        assertNull(suffixEnding(KeyEvent.KEYCODE_A, ScanSuffix.ENTER))
        // The scanner test accepts both, so it can report what the scanner sends.
        assertEquals(ScanEnding.TAB, suffixEnding(KeyEvent.KEYCODE_TAB, ScanSuffix.ENTER, acceptAny = true))
        assertEquals(ScanEnding.ENTER, suffixEnding(KeyEvent.KEYCODE_ENTER, ScanSuffix.TAB, acceptAny = true))
    }

    @Test
    fun inlineSuffixSplitsTheText() {
        assertEquals(null to "ABC", splitInline("ABC", ScanSuffix.ENTER))
        assertEquals(Scan("ABC", ScanEnding.INLINE_NEWLINE) to "", splitInline("ABC\n", ScanSuffix.ENTER))
        assertEquals(Scan("ABC", ScanEnding.INLINE_NEWLINE) to "", splitInline("ABC\r\n", ScanSuffix.ENTER))
        assertEquals(Scan("A", ScanEnding.INLINE_NEWLINE) to "B", splitInline("A\nB", ScanSuffix.ENTER))
        // A tab is only a suffix when the setting says so (or in the scanner test).
        assertEquals(null to "A\tB", splitInline("A\tB", ScanSuffix.ENTER))
        assertEquals(Scan("A", ScanEnding.INLINE_TAB) to "B", splitInline("A\tB", ScanSuffix.TAB))
        assertEquals(Scan("A", ScanEnding.INLINE_TAB) to "B\n", splitInline("A\tB\n", ScanSuffix.TAB, acceptAny = true))
    }

    @Test
    fun typedKeysBuildTheValueWhileScanning() {
        assertEquals("A", typedText("", KeyEvent.KEYCODE_A, 'A'.code))
        assertEquals("SKU-", typedText("SKU", KeyEvent.KEYCODE_MINUS, '-'.code))
        assertEquals("SK", typedText("SKU", KeyEvent.KEYCODE_DEL, 0))
        assertEquals("", typedText("", KeyEvent.KEYCODE_DEL, 0))
        assertNull(typedText("SKU", KeyEvent.KEYCODE_SHIFT_LEFT, 0)) // modifiers type nothing
        assertNull(typedText("SKU", KeyEvent.KEYCODE_ESCAPE, 27)) // control characters neither
    }

    @Test
    fun suffixSettingParsesWithEnterAsDefault() {
        assertEquals(ScanSuffix.ENTER, ScanSuffix.parse(null))
        assertEquals(ScanSuffix.ENTER, ScanSuffix.parse("bogus"))
        assertEquals(ScanSuffix.TAB, ScanSuffix.parse("TAB"))
    }
}
