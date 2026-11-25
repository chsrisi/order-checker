package com.bakingholic.orderchecker.auth

import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.device.SoftwareDeviceKeys
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiException
import com.bakingholic.orderchecker.net.ServerProfile
import java.security.Signature
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class LoginRequesterTest {
    private lateinit var server: MockWebServer
    private val keys = SoftwareDeviceKeys()
    private val seen = CopyOnWriteArrayList<Pair<String, JsonObject>>()
    private val polls = ArrayDeque<MockResponse>()
    private var create = MockResponse().setBody("""{"id":"r1","match_code":"07","expires_in":120}""")
    private val store = InMemoryTokenStore()
    private lateinit var session: SessionManager

    private val approved get() = MockResponse().setBody(
        """{"status":"approved","tokens":{"access_token":"${SessionManagerTest.jwt("alice", "sid-1", SessionManagerTest.far())}","refresh_token":"r","token_type":"bearer"}}""",
    )
    private fun status(s: String) = MockResponse().setBody("""{"status":"$s","tokens":null}""")

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                seen += request.path!! to Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                return when {
                    request.path!!.endsWith("/login-requests") -> create
                    request.path!!.endsWith("/poll") -> synchronized(polls) { polls.removeFirstOrNull() } ?: status("pending")
                    else -> MockResponse().setBody("""{"message":"ok"}""")
                }
            }
        }
        server.start()
    }

    @After
    fun tearDown() = server.shutdown()

    private fun requester(graceMillis: Long = 35_000): LoginRequester {
        val profile = ServerProfile(server.url("/").toString().trimEnd('/'))
        val http = OkHttpClient.Builder().retryOnConnectionFailure(false).build()
        val api = ApiClient(http, AppInfo(1, "2.0.0"), { profile }, AddressSelector())
        session = SessionManager(api, store)
        return LoginRequester(api, session, keys, pollMillis = 20, graceMillis = graceMillis)
    }

    private fun paths() = seen.map { it.first.substringAfter("/v2/auth/") }

    @Test
    fun approvalStoresTheTokensAndEverySignatureIsFresh() = runBlocking {
        polls += listOf(status("pending"), approved)
        var wait: LoginWait? = null
        assertEquals(LoginRequestResult.APPROVED, requester().request("alice") { wait = it })
        assertEquals("07", wait?.code)
        assertEquals("alice", session.user.value)
        assertEquals(listOf("login-requests", "login-requests/r1/poll", "login-requests/r1/poll"), paths())
        val subjects = listOf("create:alice", "poll:r1", "poll:r1")
        seen.zip(subjects).forEach { (call, subject) ->
            val nonce = call.second["nonce"]!!.jsonPrimitive.content
            val ok = Signature.getInstance("SHA256withECDSA").run {
                initVerify(keys.pair.public)
                update("oc-login-request:$subject:$nonce".toByteArray())
                verify(Base64.getDecoder().decode(call.second["signature"]!!.jsonPrimitive.content))
            }
            assertTrue(subject, ok)
        }
        assertEquals(3, seen.map { it.second["nonce"] }.toSet().size)
    }

    @Test
    fun deniedAndExpiredEndWithoutASession() = runBlocking {
        polls += status("denied")
        assertEquals(LoginRequestResult.DENIED, requester().request("alice") {})
        polls += status("expired")
        assertEquals(LoginRequestResult.EXPIRED, requester().request("alice") {})
        assertNull(store.load())
    }

    @Test
    fun networkLossAndServerErrorsWhileWaitingAreRetried() = runBlocking {
        polls += listOf(
            MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST),
            MockResponse().setResponseCode(503).setBody("""{"detail":"x"}"""),
            approved,
        )
        assertEquals(LoginRequestResult.APPROVED, requester().request("alice") {})
    }

    @Test
    fun givesUpAndCancelsAfterTheDeadline() = runBlocking {
        create = MockResponse().setBody("""{"id":"r1","match_code":"07","expires_in":0}""")
        assertEquals(LoginRequestResult.EXPIRED, requester(graceMillis = 60).request("alice") {})
        assertEquals("login-requests/r1/cancel", paths().last())
    }

    @Test
    fun cancellingTellsTheServer() = runBlocking {
        val waiting = CompletableDeferred<Unit>()
        val r = requester()
        val job = launch(Dispatchers.IO) { r.request("alice") { waiting.complete(Unit) } }
        waiting.await()
        job.cancelAndJoin()
        assertEquals("login-requests/r1/cancel", paths().last())
    }

    @Test
    fun tokensThatArriveAfterCancellingAreGivenBack() = runBlocking {
        polls += approved.setBodyDelay(400, java.util.concurrent.TimeUnit.MILLISECONDS)
        val r = requester()
        val job = launch(Dispatchers.IO) { r.request("alice") {} }
        while (paths().none { it.endsWith("poll") }) kotlinx.coroutines.delay(10)
        job.cancelAndJoin()
        assertNull(store.load())
        assertTrue(paths().toString(), "logout" in paths())
    }

    @Test
    fun aRefusedRequestReportsTheReason() = runBlocking {
        create = MockResponse().setResponseCode(403).setBody("""{"detail":"Device not registered"}""")
        try {
            requester().request("alice") {}
            fail("expected a refusal")
        } catch (e: ApiException) {
            assertEquals("Device not registered", e.detail)
        }
        assertEquals(1, seen.size)
    }
}
