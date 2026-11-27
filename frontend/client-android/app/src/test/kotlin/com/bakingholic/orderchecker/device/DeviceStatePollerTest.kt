package com.bakingholic.orderchecker.device

import com.bakingholic.orderchecker.api.model.DeviceLogoutReason
import com.bakingholic.orderchecker.auth.InMemoryTokenStore
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.auth.SessionManagerTest
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ServerProfile
import java.security.Signature
import java.util.Base64
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DeviceStatePollerTest {
    private lateinit var server: MockWebServer
    private val keys = SoftwareDeviceKeys()
    private val registrations = MemoryRegistrationStore().apply { record = RegistrationRecord("dev-1", "active", "sid-old") }
    private val tokens = InMemoryTokenStore()
    private val newAccess = SessionManagerTest.jwt("eko", "sid-new", SessionManagerTest.far())

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() = server.shutdown()

    private fun poller(pollMillis: Long = 5_000, now: Long = 1_764_000_000_000): DeviceStatePoller {
        val profile = ServerProfile(server.url("/").toString().trimEnd('/'))
        val api = ApiClient(OkHttpClient(), AppInfo(5, "2.0.4"), { profile }, AddressSelector())
        return DeviceStatePoller(api, SessionManager(api, tokens), keys, registrations, pollMillis) { now }
    }

    private fun state(assignment: String = "null", reason: String = "null") =
        MockResponse().setBody("""{"assignment":$assignment,"logout_reason":$reason}""")

    private val direct = """{"username":"eko","mode":"direct","tokens":{"access_token":"$newAccess","refresh_token":"r2","token_type":"bearer"}}"""

    @Test
    fun theRequestIsSignedOverDeviceIdAndATimedNonce() {
        val body = poller().requestFor("dev-1")
        assertTrue(Regex("^1764000000-[0-9a-f]{32}$").matches(body.nonce))
        val verifier = Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(keys.pair.public)
        verifier.update("oc-device:state:dev-1:${body.nonce}".toByteArray())
        assertTrue(verifier.verify(Base64.getDecoder().decode(body.signature)))
        assertEquals("dev-1", body.deviceId)
    }

    @Test
    fun aDirectSwitchStoresTheSession() = runBlocking {
        server.enqueue(state(direct, """{"kind":"switch","username":"eko"}"""))
        val result = poller().pollOnce()
        assertEquals(DeviceState.LoggedIn("eko", "Switched by the admin to eko."), result)
        assertEquals(newAccess, tokens.load()!!.access)
        val sent = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
        assertEquals("dev-1", sent["device_id"]!!.jsonPrimitive.content)
    }

    @Test
    fun preselectOnlyNamesTheWorker() = runBlocking {
        server.enqueue(state("""{"username":"eko","mode":"preselect","tokens":null}"""))
        assertEquals(DeviceState.Preselect("eko"), poller().pollOnce())
        assertNull(tokens.load())
    }

    @Test
    fun nothingWaitingOrAnExpiredSwitchIsIdle() = runBlocking {
        server.enqueue(state())
        server.enqueue(state(reason = """{"kind":"logout"}"""))
        val p = poller()
        assertEquals(DeviceState.Idle(), p.pollOnce())
        assertEquals(DeviceState.Idle("Logged out by the admin."), p.pollOnce())
    }

    @Test
    fun networkLossAndServerErrorsAreRetried() = runBlocking {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        server.enqueue(MockResponse().setResponseCode(503))
        server.enqueue(MockResponse().setResponseCode(429).setBody("""{"detail":"Polling too fast"}"""))
        val p = poller()
        assertNull(p.pollOnce())
        assertNull(p.pollOnce())
        assertNull(p.pollOnce())
    }

    @Test
    fun revokedAndClockOffAreFinal() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"Device revoked"}"""))
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"Nonce out of time"}"""))
        val p = poller()
        assertEquals(DeviceState.Revoked, p.pollOnce())
        assertEquals(DeviceState.ClockOff, p.pollOnce())
    }

    @Test
    fun anUnregisteredDeviceDoesNotPoll() = runBlocking {
        registrations.record = null
        assertNull(poller().pollOnce())
        assertEquals(0, server.requestCount)
    }

    @Test
    fun runPassesOnlyNewsAndStopsWhenCancelled() = runBlocking {
        server.enqueue(state())
        server.enqueue(state("""{"username":"eko","mode":"preselect","tokens":null}"""))
        repeat(20) { server.enqueue(state()) }
        val seen = mutableListOf<DeviceState>()
        val first = CompletableDeferred<Unit>()
        val job = launch(Dispatchers.IO) {
            poller(pollMillis = 10).run {
                seen += it
                first.complete(Unit)
                true
            }
        }
        withTimeout(5_000) { first.await() }
        job.cancelAndJoin()
        val count = server.requestCount
        delay(100)
        assertEquals(count, server.requestCount) // no poll after cancelling (background, logged in)
        assertEquals(listOf<DeviceState>(DeviceState.Preselect("eko")), seen)
    }

    @Test
    fun runStopsWhenTheHandlerSaysSo() = runBlocking {
        server.enqueue(state("""{"username":"eko","mode":"preselect","tokens":null}"""))
        poller(pollMillis = 10).run { false }
        assertEquals(1, server.requestCount)
    }

    @Test
    fun tokensArrivingAfterCancelAreGivenBack() = runBlocking {
        server.enqueue(state(direct).setBodyDelay(300, TimeUnit.MILLISECONDS))
        server.enqueue(MockResponse().setBody("{}")) // the logout that gives the session back
        val job = launch(Dispatchers.IO) { poller().pollOnce() }
        assertEquals("/v2/device/state", server.takeRequest(5, TimeUnit.SECONDS)!!.path)
        job.cancelAndJoin() // while the answer is still on its way
        assertNull(tokens.load())
        assertEquals("/v2/auth/logout", server.takeRequest(5, TimeUnit.SECONDS)!!.path)
    }

    @Test
    fun reasonTexts() {
        assertNull(logoutReasonText(null))
        assertEquals("Logged out by the admin.", logoutReasonText(DeviceLogoutReason(DeviceLogoutReason.Kind.LOGOUT)))
        assertEquals(
            "Switched by the admin to eko.",
            logoutReasonText(DeviceLogoutReason(DeviceLogoutReason.Kind.SWITCH, "eko")),
        )
    }
}
