package com.bakingholic.orderchecker.device

import com.bakingholic.orderchecker.api.model.DeviceLogoutReason
import com.bakingholic.orderchecker.api.model.DeviceStateAssignment
import com.bakingholic.orderchecker.api.model.DeviceStateRequest
import com.bakingholic.orderchecker.api.model.DeviceStateResponse
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.UpgradeRequiredException
import java.io.IOException
import java.security.SecureRandom
import java.util.Base64
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/** What one state poll brought (T8.7, backend T8.4a). */
sealed interface DeviceState {
    /** Why the admin logged this device out, if the server said so (W8). */
    val logoutReason: String?

    /** Nothing waiting. */
    data class Idle(override val logoutReason: String? = null) : DeviceState

    /** The admin logged [username] in on this device: the session is already stored. */
    data class LoggedIn(val username: String, override val logoutReason: String? = null) : DeviceState

    /** The admin chose [username]: select them and ask for the password. */
    data class Preselect(val username: String, override val logoutReason: String? = null) : DeviceState

    /** The device was revoked: stop polling. */
    data object Revoked : DeviceState {
        override val logoutReason: String? = null
    }

    /** The server refuses this device's clock (more than 5 minutes off): switches can't arrive. */
    data object ClockOff : DeviceState {
        override val logoutReason: String? = null
    }
}

/** The line under "Session ended" (W8). */
fun logoutReasonText(reason: DeviceLogoutReason?): String? = when (reason?.kind) {
    null -> null
    DeviceLogoutReason.Kind.LOGOUT -> "Logged out by the admin."
    DeviceLogoutReason.Kind.SWITCH ->
        reason.username?.let { "Switched by the admin to $it." } ?: "Switched by the admin."
}

/**
 * Polls `POST /v2/device/state` from the login screen: signed with the device key over
 * `oc-device:state:<device_id>:<nonce>`, the nonce starting with this device's Unix time. A
 * direct switch's tokens are stored at once, or given back when the poll was cancelled meanwhile.
 */
class DeviceStatePoller(
    private val api: ApiClient,
    private val session: SessionManager,
    private val keys: DeviceKeys,
    private val registrations: RegistrationStore,
    val pollMillis: Long = 5_000,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val random = SecureRandom()

    /** `<unix seconds>-<32 hex>`, as the backend's nonce pattern wants. */
    fun nonce(): String {
        val bytes = ByteArray(16).also(random::nextBytes)
        return "${nowMillis() / 1000}-" + bytes.joinToString("") { "%02x".format(it) }
    }

    fun requestFor(deviceId: String, nonce: String = nonce()): DeviceStateRequest {
        val signature = keys.sign("oc-device:state:$deviceId:$nonce".toByteArray(Charsets.UTF_8))
        return DeviceStateRequest(
            deviceId = deviceId,
            nonce = nonce,
            signature = Base64.getEncoder().encodeToString(signature),
        )
    }

    /**
     * One poll. Null when there is nothing to poll for yet (never registered) or the answer is
     * worth retrying (offline, server error, too fast).
     */
    suspend fun pollOnce(): DeviceState? {
        val deviceId = registrations.load()?.deviceId ?: return null
        val caller = coroutineContext
        val body = withContext(Dispatchers.Default) {
            json.encodeToString(DeviceStateRequest.serializer(), requestFor(deviceId))
        }
        // Not cancellable: tokens that were handed out must be stored or given back.
        return withContext(NonCancellable) {
            val response = try {
                api.send(ApiRequest("POST", "/v2/device/state", jsonBody = body))
            } catch (e: IOException) {
                return@withContext null
            } catch (e: UpgradeRequiredException) {
                return@withContext null // the app shows its update screen
            }
            when {
                response.isSuccessful -> handle(json.decodeFromString(DeviceStateResponse.serializer(), response.body), caller.isActive)
                response.code == 403 && api.detail(response.body) == "Device revoked" -> DeviceState.Revoked
                response.code == 400 && api.detail(response.body) == "Nonce out of time" -> DeviceState.ClockOff
                else -> null
            }
        }
    }

    private suspend fun handle(state: DeviceStateResponse, wanted: Boolean): DeviceState {
        val reason = logoutReasonText(state.logoutReason)
        val assignment = state.assignment ?: return DeviceState.Idle(reason)
        return when (assignment.mode) {
            DeviceStateAssignment.Mode.DIRECT -> {
                val tokens = assignment.tokens ?: return DeviceState.Idle(reason)
                if (!wanted) {
                    session.giveBack(tokens)
                    DeviceState.Idle(reason)
                } else {
                    session.accept(tokens)
                    DeviceState.LoggedIn(assignment.username, reason)
                }
            }
            DeviceStateAssignment.Mode.PRESELECT -> DeviceState.Preselect(assignment.username, reason)
        }
    }

    /**
     * Polls every [pollMillis] until cancelled or until [onState] returns false. Answers
     * without news ([DeviceState.Idle] without a reason) are not passed on.
     */
    suspend fun run(onState: suspend (DeviceState) -> Boolean) {
        while (coroutineContext.isActive) {
            val state = pollOnce()
            if (state != null && state != DeviceState.Idle()) {
                if (!onState(state)) return
            }
            delay(pollMillis)
        }
    }
}
