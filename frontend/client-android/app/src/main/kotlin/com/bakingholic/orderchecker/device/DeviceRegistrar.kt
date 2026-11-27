package com.bakingholic.orderchecker.device

import com.bakingholic.orderchecker.api.model.DeviceRegisterRequest
import com.bakingholic.orderchecker.api.model.DeviceResponse
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.NotLoggedInException
import com.bakingholic.orderchecker.net.UpgradeRequiredException
import com.bakingholic.orderchecker.ws.Backoff
import java.io.IOException
import java.util.Base64
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** What the settings screen shows about this device. */
sealed interface DeviceStatus {
    data object Unregistered : DeviceStatus

    data object Registering : DeviceStatus

    /** Offline or server error: retried automatically. */
    data class Retrying(val reason: String) : DeviceStatus

    data class Registered(val deviceId: String, val status: String) : DeviceStatus

    /** The server revoked this device (403): final; a recovered scanner is reinstalled (W7). */
    data object Revoked : DeviceStatus

    data class Rejected(val reason: String) : DeviceStatus
}

/** Last successful registration, kept so a restart knows which session is already bound. */
@Serializable
data class RegistrationRecord(val deviceId: String, val status: String, val sessionId: String)

interface RegistrationStore {
    suspend fun load(): RegistrationRecord?

    suspend fun save(record: RegistrationRecord)
}

/**
 * Registers the device after every login (T6.13, backend T6.6): the public key, model, Android
 * version and versionCode, with a signature over the session id. Registration is idempotent on
 * the server, so retries after a network error are safe.
 */
class DeviceRegistrar(
    private val session: SessionManager,
    private val keys: DeviceKeys,
    private val appInfo: AppInfo,
    private val model: String,
    private val androidVersion: String,
    private val store: RegistrationStore,
    private val backoff: Backoff = Backoff(baseMillis = 5_000, capMillis = 5 * 60_000L),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val _status = MutableStateFlow<DeviceStatus>(DeviceStatus.Unregistered)
    val status: StateFlow<DeviceStatus> = _status

    /** The request body: what the backend verifies (signature over the UTF-8 `sid`). */
    fun requestFor(sessionId: String): DeviceRegisterRequest {
        val signature = keys.sign(sessionId.toByteArray(Charsets.UTF_8))
        return DeviceRegisterRequest(
            androidVersion = androidVersion,
            appVersionCode = appInfo.versionCode,
            model = model,
            publicKey = keys.publicKeyBase64(),
            signature = Base64.getEncoder().encodeToString(signature),
        )
    }

    /** One attempt. Returns true when done (success or a final answer), false to retry. */
    suspend fun registerOnce(): Boolean {
        val sid = session.sessionId() ?: return true
        val saved = store.load()
        if (saved != null && saved.sessionId == sid) {
            _status.value = DeviceStatus.Registered(saved.deviceId, saved.status)
            return true
        }
        _status.value = DeviceStatus.Registering
        val body = json.encodeToString(DeviceRegisterRequest.serializer(), requestFor(sid))
        val response = try {
            session.authorized(ApiRequest("POST", "/v2/device/register", jsonBody = body))
        } catch (e: NotLoggedInException) {
            _status.value = DeviceStatus.Unregistered
            return true
        } catch (e: UpgradeRequiredException) {
            return true
        } catch (e: IOException) {
            _status.value = DeviceStatus.Retrying(e.message ?: "offline")
            return false
        }
        return when {
            response.isSuccessful -> {
                val device = json.decodeFromString(DeviceResponse.serializer(), response.body)
                store.save(RegistrationRecord(device.id, device.status, sid))
                _status.value = DeviceStatus.Registered(device.id, device.status)
                true
            }
            response.code == 403 -> {
                // The server also ended this session (T8.1, W9): log out here, no retry.
                _status.value = DeviceStatus.Revoked
                session.endBecauseDeviceRevoked()
                true
            }
            response.code in 400..499 -> {
                _status.value = DeviceStatus.Rejected("HTTP ${response.code}")
                true
            }
            else -> {
                _status.value = DeviceStatus.Retrying("HTTP ${response.code}")
                false
            }
        }
    }

    /** Retries with backoff until done; run it in a coroutine tied to the login. */
    suspend fun registerWithRetry() {
        backoff.reset()
        while (!registerOnce()) delay(backoff.next())
    }
}
