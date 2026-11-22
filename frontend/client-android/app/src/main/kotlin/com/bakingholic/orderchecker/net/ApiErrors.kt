package com.bakingholic.orderchecker.net

import java.io.IOException

/** No address of the profile answered. */
class ServerUnreachableException(cause: Throwable? = null) : IOException("Server unreachable", cause)

/** The backend wants a newer app (HTTP 426 / WS close 4426). */
class UpgradeRequiredException(val minSupportedVersionCode: Int?) : Exception("Client update required")

/** No valid session any more: the app must show the login screen. */
class NotLoggedInException : Exception("Not logged in")

/** A backend answer other than success, with its `detail`. */
class ApiException(val code: Int, val detail: String?) : Exception("HTTP $code: ${detail ?: ""}")

/** App-wide events the UI reacts to. */
sealed interface AppEvent {
    data object LoggedOut : AppEvent

    data class UpgradeRequired(val minSupportedVersionCode: Int?) : AppEvent
}
