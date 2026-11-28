package com.bakingholic.orderchecker.auth

import com.bakingholic.orderchecker.api.model.LoginRequestCreate
import com.bakingholic.orderchecker.api.model.LoginRequestCreated
import com.bakingholic.orderchecker.api.model.LoginRequestPoll
import com.bakingholic.orderchecker.api.model.LoginRequestProof
import com.bakingholic.orderchecker.device.DeviceKeys
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiException
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.ApiResponse
import java.io.IOException
import java.security.SecureRandom
import java.util.Base64
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/** A request an admin has to decide until [deadlineMillis] (the requester's clock). */
data class LoginWait(val username: String, val code: String, val deadlineMillis: Long)

enum class LoginRequestResult { APPROVED, DENIED, EXPIRED }

/**
 * Asks an admin to approve a login (T6.23): creates a request signed with the device key, then
 * polls until it is decided. Cancelling the coroutine cancels the request.
 */
class LoginRequester(
    private val api: ApiClient,
    private val session: SessionManager,
    private val keys: DeviceKeys,
    private val pollMillis: Long = 2_000,
    private val graceMillis: Long = 35_000,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val random = SecureRandom()

    suspend fun request(username: String, onWaiting: (LoginWait) -> Unit): LoginRequestResult {
        val proof = proof("create", username)
        val body = LoginRequestCreate(
            nonce = proof.nonce,
            publicKey = withContext(Dispatchers.Default) { keys.publicKeyBase64() },
            signature = proof.signature,
            username = username,
        )
        val created = json.decodeFromString(
            LoginRequestCreated.serializer(),
            post("", json.encodeToString(LoginRequestCreate.serializer(), body)).body,
        )
        var ended = false
        try {
            val deadline = nowMillis() + created.expiresIn * 1_000L
            onWaiting(LoginWait(username, created.matchCode, deadline))
            // An approval in the last second can still be collected a little later.
            while (nowMillis() < deadline + graceMillis) {
                delay(pollMillis)
                val result = pollOnce(created.id) ?: continue
                ended = true
                return result
            }
            return LoginRequestResult.EXPIRED
        } finally {
            if (!ended) withContext(NonCancellable) { runCatching { post("/${created.id}/cancel", proofBody("cancel", created.id)) } }
        }
    }

    /** Null while undecided or while the server cannot be reached. */
    private suspend fun pollOnce(id: String): LoginRequestResult? {
        val caller = coroutineContext
        // Not cancellable: tokens that were handed out must be stored or given back.
        val result = withContext(NonCancellable) {
            val poll = try {
                json.decodeFromString(LoginRequestPoll.serializer(), post("/$id/poll", proofBody("poll", id)).body)
            } catch (e: IOException) {
                return@withContext null
            } catch (e: ApiException) {
                if (e.code >= 500) return@withContext null
                throw e
            }
            val tokens = poll.tokens
            when {
                poll.status == "approved" && tokens != null -> {
                    if (caller.isActive) session.accept(tokens) else session.giveBack(tokens)
                    LoginRequestResult.APPROVED
                }
                poll.status == "denied" -> LoginRequestResult.DENIED
                poll.status == "expired" -> LoginRequestResult.EXPIRED
                else -> null
            }
        }
        if (result != LoginRequestResult.APPROVED) caller.ensureActive()
        return result
    }

    private suspend fun post(path: String, body: String): ApiResponse {
        val response = api.send(ApiRequest("POST", "/v2/auth/login-requests$path", jsonBody = body))
        if (!response.isSuccessful) throw ApiException(response.code, api.detail(response.body))
        return response
    }

    private suspend fun proofBody(action: String, subject: String): String =
        json.encodeToString(LoginRequestProof.serializer(), proof(action, subject))

    private suspend fun proof(action: String, subject: String): LoginRequestProof = withContext(Dispatchers.Default) {
        val nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(18).also(random::nextBytes))
        val signature = keys.sign("oc-login-request:$action:$subject:$nonce".toByteArray(Charsets.UTF_8))
        LoginRequestProof(nonce = nonce, signature = Base64.getEncoder().encodeToString(signature))
    }
}
