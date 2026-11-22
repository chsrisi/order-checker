package com.bakingholic.orderchecker.settings

/**
 * Hidden settings unlock (P-13): a 5 s long-press on the version label, then this PIN. The PIN
 * comes from local build configuration (`oc.settingsPin`), never from git. A build without a
 * PIN cannot open the settings.
 */
class PinGate(private val expected: String) {
    val enabled: Boolean get() = expected.isNotBlank()

    fun accepts(input: String): Boolean = enabled && constantTimeEquals(input.trim(), expected)

    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var diff = 0
        for (i in a.indices) diff = diff or (a[i].code xor b[i].code)
        return diff == 0
    }

    companion object {
        const val LONG_PRESS_MILLIS = 5_000L
    }
}
