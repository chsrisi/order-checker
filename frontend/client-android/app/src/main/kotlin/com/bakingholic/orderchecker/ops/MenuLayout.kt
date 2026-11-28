package com.bakingholic.orderchecker.ops

/**
 * Height in dp of each Home menu button for [availableDp] of screen: they share it, 72 dp at most
 * (the emulator baseline) and 48 dp at least (the touch minimum); below that the menu scrolls.
 * Real scanners are shorter than the emulator (device day 1: Finder was cut to half).
 */
fun menuButtonHeight(availableDp: Float, count: Int, paddingDp: Float = 12f, gapDp: Float = 10f): Float {
    if (count <= 0) return MENU_BUTTON_MAX
    val share = (availableDp - 2 * paddingDp - (count - 1) * gapDp) / count
    return share.coerceIn(MENU_BUTTON_MIN, MENU_BUTTON_MAX)
}

const val MENU_BUTTON_MIN = 48f
const val MENU_BUTTON_MAX = 72f
