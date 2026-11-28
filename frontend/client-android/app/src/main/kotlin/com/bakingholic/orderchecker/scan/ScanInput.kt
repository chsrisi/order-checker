package com.bakingholic.orderchecker.scan

import android.view.KeyEvent

/** The key a keyboard-wedge scanner sends after each barcode (T6.15a; the MT67 default is Enter). */
enum class ScanSuffix(val label: String) {
    ENTER("Enter"),
    TAB("Tab"),
    ;

    companion object {
        fun parse(raw: String?): ScanSuffix = entries.firstOrNull { it.name == raw } ?: ENTER
    }
}

/** What ended a scan: a hardware key, the soft keyboard's Done, or a suffix typed into the text. */
enum class ScanEnding(val label: String) {
    ENTER("Enter key"),
    TAB("Tab key"),
    IME("keyboard Done"),
    INLINE_NEWLINE("newline in text"),
    INLINE_TAB("tab in text"),
}

data class Scan(val value: String, val ending: ScanEnding)

/** The hardware key that ends a scan, or null when [keyCode] is not a suffix. */
fun suffixEnding(keyCode: Int, suffix: ScanSuffix, acceptAny: Boolean = false): ScanEnding? = when (keyCode) {
    KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER ->
        ScanEnding.ENTER.takeIf { acceptAny || suffix == ScanSuffix.ENTER }
    KeyEvent.KEYCODE_TAB -> ScanEnding.TAB.takeIf { acceptAny || suffix == ScanSuffix.TAB }
    else -> null
}

/**
 * The field text after one key while scanning (the field is read-only then, so keys are applied
 * here): a printable character is appended, Backspace removes the last one, anything else (Shift,
 * arrows, function keys) is ignored and returns null.
 */
fun typedText(current: String, keyCode: Int, codePoint: Int): String? = when {
    keyCode == KeyEvent.KEYCODE_DEL -> current.dropLast(1)
    codePoint > 0 && !Character.isISOControl(codePoint) -> current + String(Character.toChars(codePoint))
    else -> null
}

/**
 * A scanner in "fill text" mode puts the suffix into the text itself. Splits [text] at the first
 * suffix character: (completed value, ending) and the remainder to keep in the field.
 */
fun splitInline(text: String, suffix: ScanSuffix, acceptAny: Boolean = false): Pair<Scan?, String> {
    val newline = text.indexOfFirst { it == '\n' || it == '\r' }
        .takeIf { it >= 0 && (acceptAny || suffix == ScanSuffix.ENTER) }
    val tab = text.indexOf('\t').takeIf { it >= 0 && (acceptAny || suffix == ScanSuffix.TAB) }
    val cut = listOfNotNull(newline, tab).minOrNull() ?: return null to text
    val ending = if (cut == newline) ScanEnding.INLINE_NEWLINE else ScanEnding.INLINE_TAB
    var rest = text.substring(cut + 1)
    if (text[cut] == '\r' && rest.startsWith('\n')) rest = rest.substring(1)
    return Scan(text.substring(0, cut), ending) to rest
}

/**
 * Filters submitted values: trims them, ignores blanks, and drops the same value submitted again
 * within [dedupeWindowMs] (a wedge firing twice). A repeat after the window is a real rescan.
 */
class ScanGate(
    private val dedupeWindowMs: Long = 300,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private var last: String? = null
    private var lastAt = 0L

    fun accept(raw: String): String? {
        val value = raw.trim()
        if (value.isEmpty()) return null
        val now = clock()
        if (value == last && now - lastAt < dedupeWindowMs) return null
        last = value
        lastAt = now
        return value
    }

    /**
     * [accept] unless the screen is still saving the previous scan ([busy]): that scan is refused,
     * not queued, and not remembered, so scanning it again right after the save goes through.
     */
    fun accept(raw: String, busy: Boolean): String? = if (busy) null else accept(raw)
}

/** The status line under a scan field: replaces v1's modal alerts and success toasts (C5). */
sealed interface ScanFeedback {
    data object None : ScanFeedback

    data class Ok(val message: String) : ScanFeedback

    data class Warning(val message: String) : ScanFeedback

    data class Error(val message: String) : ScanFeedback
}
