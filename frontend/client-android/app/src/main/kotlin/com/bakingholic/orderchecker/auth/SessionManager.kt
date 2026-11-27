package com.bakingholic.orderchecker.auth

import com.bakingholic.orderchecker.api.model.RefreshTokenRequest
import com.bakingholic.orderchecker.api.model.Token
import com.bakingholic.orderchecker.api.model.UserAuth
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiException
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.ApiResponse
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.NotLoggedInException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json

/**
 * Login, refresh and logout, plus authorized calls with the T6.11 rules: refresh early when the
 * access token is about to expire; on 401 one refresh (shared by every caller in flight) and one
 * retry; when that fails, log out locally and report [AppEvent.LoggedOut].
 */
class SessionManager(
    private val api: ApiClient,
    private val store: TokenStore,
    private val onEvent: (AppEvent) -> Unit = {},
    private val onLocalLogout: suspend () -> Unit = {},
    private val nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val refreshLock = Mutex()
    private val _user = MutableStateFlow<String?>(null)

    /** Username of the current session, or null when logged out. */
    val user: StateFlow<String?> = _user

    suspend fun restore(): Boolean {
        val tokens = store.load() ?: return false
        _user.value = AccessClaims.parse(tokens.access).subject
        return true
    }

    suspend fun login(username: String, password: String) {
        val body = json.encodeToString(UserAuth.serializer(), UserAuth(password = password, username = username))
        val response = api.send(ApiRequest("POST", "/v2/auth/login", jsonBody = body))
        if (!response.isSuccessful) throw ApiException(response.code, api.detail(response.body))
        saveTokens(response)
    }

    /** Ends the session on the server (best effort) and always locally. */
    suspend fun logout() {
        store.load()?.let { endOnServer(it.refresh) }
        clearLocal(report = false)
    }

    /** Ends a session that was issued but is not wanted any more (best effort). */
    suspend fun giveBack(token: Token) = endOnServer(token.refreshToken)

    private suspend fun endOnServer(refresh: String) {
        runCatching {
            api.send(
                ApiRequest(
                    "POST",
                    "/v2/auth/logout",
                    jsonBody = json.encodeToString(RefreshTokenRequest.serializer(), RefreshTokenRequest(refresh)),
                ),
            )
        }
    }

    /** Current access token, refreshed first when it expires within a minute. */
    suspend fun accessToken(): String {
        val tokens = store.load() ?: throw NotLoggedInException()
        if (AccessClaims.parse(tokens.access).expiresWithin(60, nowEpochSeconds())) {
            return refreshAfter(tokens.access)
        }
        return tokens.access
    }

    /** The session id (`sid`) of the current access token. */
    suspend fun sessionId(): String? = store.load()?.let { AccessClaims.parse(it.access).sessionId }

    /** An authorized call with the 401 → refresh → retry-once rule. */
    suspend fun authorized(request: ApiRequest): ApiResponse {
        val token = accessToken()
        val first = api.send(request, token)
        if (first.code != 401) return first
        val fresh = refreshAfter(token)
        val second = api.send(request, fresh)
        if (second.code == 401) {
            clearLocal(report = true)
            throw NotLoggedInException()
        }
        return second
    }

    /**
     * Refresh unless another caller already replaced [stale]. One refresh at a time; callers
     * that waited reuse its result. A rejected refresh logs out; a network error propagates
     * (the session may still be fine).
     */
    suspend fun refreshAfter(stale: String): String =
        refreshLock.withLock {
            val current = store.load() ?: throw NotLoggedInException()
            if (current.access != stale) return current.access
            val response = api.send(
                ApiRequest(
                    "POST",
                    "/v2/auth/refresh",
                    jsonBody = json.encodeToString(RefreshTokenRequest.serializer(), RefreshTokenRequest(current.refresh)),
                ),
            )
            if (response.code in 400..499) {
                clearLocal(report = true)
                throw NotLoggedInException()
            }
            if (!response.isSuccessful) throw ApiException(response.code, api.detail(response.body))
            saveTokens(response).access
        }

    private suspend fun saveTokens(response: ApiResponse): Tokens =
        accept(json.decodeFromString(Token.serializer(), response.body))

    /** Starts (or continues) the local session with this token pair. */
    suspend fun accept(token: Token): Tokens {
        val tokens = Tokens(token.accessToken, token.refreshToken)
        store.save(tokens)
        _user.value = AccessClaims.parse(tokens.access).subject
        return tokens
    }

    private suspend fun clearLocal(report: Boolean) {
        store.clear()
        _user.value = null
        onLocalLogout()
        if (report) onEvent(AppEvent.LoggedOut)
    }
}
