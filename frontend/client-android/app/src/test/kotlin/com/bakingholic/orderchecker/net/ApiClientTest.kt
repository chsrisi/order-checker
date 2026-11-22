package com.bakingholic.orderchecker.net

import com.bakingholic.orderchecker.core.AppInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class ApiClientTest {
    private lateinit var primary: MockWebServer
    private lateinit var fallback: MockWebServer
    private val events = mutableListOf<AppEvent>()
    private val http = OkHttpClient.Builder().connectTimeout(1, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()

    @Before
    fun setUp() {
        primary = MockWebServer().apply { start() }
        fallback = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        primary.shutdown()
        fallback.shutdown()
    }

    private fun client(profile: ServerProfile) =
        ApiClient(http, AppInfo(7, "2.0.6"), { profile }, AddressSelector(), { events += it }, Dispatchers.Unconfined)

    private fun base(server: MockWebServer) = server.url("/").toString().trimEnd('/')

    @Test
    fun sendsVersionAndAccessHeadersAndEncodesQuery() = runTest {
        primary.enqueue(MockResponse().setBody("[]"))
        val profile = ServerProfile(base(primary), accessClientId = "id", accessClientSecret = "secret")
        client(profile).send(ApiRequest("GET", "/v2/items/find", mapOf("query" to "A 1&b=2")), bearer = "tok")
        val recorded = primary.takeRequest()
        assertEquals("7", recorded.getHeader("X-Client-Version"))
        assertEquals("id", recorded.getHeader("CF-Access-Client-Id"))
        assertEquals("secret", recorded.getHeader("CF-Access-Client-Secret"))
        assertEquals("Bearer tok", recorded.getHeader("Authorization"))
        assertEquals("A 1&b=2", recorded.requestUrl!!.queryParameter("query"))
        assertTrue(recorded.path!!.contains("query=A%201%26b%3D2"))
    }

    @Test
    fun connectionFailureMovesToTheFallback() = runTest {
        primary.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        fallback.enqueue(MockResponse().setBody("{}"))
        val api = client(ServerProfile(base(primary), base(fallback)))
        val answer = api.send(ApiRequest("GET", "/v2/meta"))
        assertEquals(base(fallback), answer.address)
        assertTrue(api.selector.onFallback())
    }

    @Test
    fun http4xxIsAnAnswerAndNeverSwitches() = runTest {
        primary.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Not found"}"""))
        val api = client(ServerProfile(base(primary), base(fallback)))
        val answer = api.send(ApiRequest("GET", "/v2/items/find"))
        assertEquals(404, answer.code)
        assertEquals(0, fallback.requestCount)
    }

    @Test
    fun cloudflareOriginErrorAndAccessBlockCountAsUnreachable() = runTest {
        primary.enqueue(MockResponse().setResponseCode(522))
        fallback.enqueue(MockResponse().setBody("{}"))
        val api = client(ServerProfile(base(primary), base(fallback)))
        assertEquals(base(fallback), api.send(ApiRequest("GET", "/v2/meta")).address)

        primary.enqueue(MockResponse().setResponseCode(403).addHeader("cf-mitigated", "challenge"))
        fallback.enqueue(MockResponse().setBody("{}"))
        val api2 = client(ServerProfile(base(primary), base(fallback)))
        assertEquals(base(fallback), api2.send(ApiRequest("GET", "/v2/meta")).address)
    }

    @Test
    fun upgradeRequiredIsRaisedAndReported() = runTest {
        primary.enqueue(
            MockResponse().setResponseCode(426).setBody("""{"detail":"Client update required","min_supported_version_code":9}"""),
        )
        try {
            client(ServerProfile(base(primary))).send(ApiRequest("POST", "/v2/outbound", jsonBody = "{}"))
            fail("expected 426")
        } catch (e: UpgradeRequiredException) {
            assertEquals(9, e.minSupportedVersionCode)
        }
        assertEquals(listOf<AppEvent>(AppEvent.UpgradeRequired(9)), events)
    }

    @Test
    fun noAddressAnsweringIsServerUnreachable() = runTest {
        primary.shutdown()
        try {
            client(ServerProfile(base(primary))).send(ApiRequest("GET", "/v2/meta"))
            fail("expected unreachable")
        } catch (e: ServerUnreachableException) {
            assertNull(null)
        }
    }

    @Test
    fun probeMovesBackToThePrimaryWhenItAnswers() = runTest {
        primary.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        fallback.enqueue(MockResponse().setBody("{}"))
        val api = client(ServerProfile(base(primary), base(fallback)))
        api.send(ApiRequest("GET", "/v2/meta"))
        primary.enqueue(MockResponse().setBody("{}"))
        api.probePrimaryIfDue()
        assertEquals(base(primary), api.selector.order().first())
    }
}
