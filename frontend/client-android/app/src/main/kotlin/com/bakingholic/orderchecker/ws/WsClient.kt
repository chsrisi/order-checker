package com.bakingholic.orderchecker.ws

import com.bakingholic.orderchecker.api.model.WebSocketTicketResponse
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.NotLoggedInException
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.net.UpgradeRequiredException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.onTimeout
import kotlinx.coroutines.selects.select
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * Keeps one `/v2/ws` connection while logged in: a fresh ticket per attempt, the address the
 * last HTTP call used, unlimited [Backoff], an immediate retry on network change ([kick]).
 */
class WsClient(
    private val http: OkHttpClient,
    private val session: SessionManager,
    private val appInfo: AppInfo,
    private val profile: () -> ServerProfile,
    private val activeAddress: () -> String?,
    private val onEvent: (AppEvent) -> Unit,
    private val scope: CoroutineScope,
) {
    enum class State { DISCONNECTED, CONNECTING, CONNECTED }

    private val json = Json { ignoreUnknownKeys = true }
    private val _state = MutableStateFlow(State.DISCONNECTED)
    val state: StateFlow<State> = _state
    private val _frames = MutableSharedFlow<WsFrame>(extraBufferCapacity = 64)
    val frames: SharedFlow<WsFrame> = _frames
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private var job: Job? = null
    private var socket: WebSocket? = null

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch { loop() }
    }

    fun stop() {
        job?.cancel()
        job = null
        socket?.close(1000, null)
        socket = null
        _state.value = State.DISCONNECTED
    }

    /** Sends a command frame (`{"command": ...}`) on the open socket; false when not connected. */
    fun send(command: String): Boolean = socket?.send("""{"command":"$command"}""") ?: false

    /** Network came back: skip the remaining backoff delay. */
    fun kick() {
        wake.trySend(Unit)
    }

    private suspend fun loop() {
        val backoff = Backoff()
        var retriedTicket = false
        while (scope.isActive) {
            _state.value = State.CONNECTING
            val code = try {
                val ticket = json.decodeFromString(
                    WebSocketTicketResponse.serializer(),
                    session.authorized(ApiRequest("POST", "/v2/auth/ws-token")).also {
                        if (!it.isSuccessful) throw IllegalStateException("ws-token ${it.code}")
                    }.body,
                )
                connectOnce(ticket.token) { backoff.reset(); retriedTicket = false }
            } catch (e: NotLoggedInException) {
                _state.value = State.DISCONNECTED
                return
            } catch (e: UpgradeRequiredException) {
                _state.value = State.DISCONNECTED
                return
            } catch (e: Exception) {
                -1
            }
            _state.value = State.DISCONNECTED
            when (CloseRules.action(code, retriedTicket)) {
                CloseAction.UPDATE_REQUIRED -> {
                    onEvent(AppEvent.UpgradeRequired(null))
                    return
                }
                CloseAction.LOG_OUT -> {
                    // Confirm with an authorized call: a dead session answers 401 and logs out.
                    runCatching { session.authorized(ApiRequest("GET", "/v2/meta")) }
                    retriedTicket = false
                }
                CloseAction.NEW_TICKET_NOW -> {
                    retriedTicket = true
                    continue
                }
                CloseAction.RECONNECT -> Unit
            }
            val delayMillis = backoff.next()
            select<Unit> {
                wake.onReceive { }
                onTimeout(delayMillis) { }
            }
        }
    }

    /** Opens the socket and suspends until it closes; returns the close code (-1 on failure). */
    private suspend fun connectOnce(ticket: String, onOpen: () -> Unit): Int {
        val address = activeAddress() ?: profile().addresses.first()
        val wsUrl = address.replaceFirst("http", "ws") + "/v2/ws?token=" + ticket
        val closed = CompletableDeferred<Int>()
        val builder = Request.Builder().url(wsUrl).header("X-Client-Version", appInfo.clientVersionHeader)
        profile().accessHeaders.forEach { (k, v) -> builder.header(k, v) }
        socket = http.newWebSocket(
            builder.build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    _state.value = State.CONNECTED
                    onOpen()
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    _frames.tryEmit(WsFrame.parse(text))
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, null)
                    closed.complete(code)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    closed.complete(code)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    closed.complete(-1)
                }
            },
        )
        return try {
            closed.await()
        } finally {
            socket = null
        }
    }
}
