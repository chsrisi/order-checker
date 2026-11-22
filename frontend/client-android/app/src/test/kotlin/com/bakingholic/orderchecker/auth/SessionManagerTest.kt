package com.bakingholic.orderchecker.auth

import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.NotLoggedInException
import com.bakingholic.orderchecker.net.ServerProfile
import java.util.Base64
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

/** A fake backend: one valid access token at a time; refresh rotates it. */
class SessionManagerTest {
    private lateinit var server: MockWebServer
    private val refreshes = AtomicInteger()
    private val events = mutableListOf<AppEvent>()

    @Volatile private var validAccess = jwt("alice", "sid-1", far())

    @Volatile private var refreshAllowed = true

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
                "/v2/auth/login" -> tokens()
                "/v2/auth/refresh" -> {
                    refreshes.incrementAndGet()
                    Thread.sleep(100) // keep the refresh in flight while others queue up
                    if (refreshAllowed) {
                        validAccess = jwt("alice", "sid-1", far(), nonce = refreshes.get())
                        tokens()
                    } else {
                        MockResponse().setResponseCode(401).setBody("""{"detail":"Invalid refresh token"}""")
                    }
                }
                "/v2/auth/logout" -> MockResponse().setBody("""{"message":"ok"}""")
                else ->
                    if (request.getHeader("Authorization") == "Bearer $validAccess") {
                        MockResponse().setBody("[]")
                    } else {
                        MockResponse().setResponseCode(401).setBody("""{"detail":"Invalid access token"}""")
                    }
            }
        }
        server.start()
    }

    @After
    fun tearDown() = server.shutdown()

    private fun tokens() = MockResponse().setBody("""{"access_token":"$validAccess","refresh_token":"r-${refreshes.get()}","token_type":"bearer"}""")

    private fun session(store: TokenStore = InMemoryTokenStore()): SessionManager {
        val profile = ServerProfile(server.url("/").toString().trimEnd('/'))
        val api = ApiClient(OkHttpClient(), AppInfo(1, "2.0.0"), { profile }, AddressSelector(), { events += it })
        return SessionManager(api, store, onEvent = { events += it })
    }

    @Test
    fun loginStoresTokensAndUser() = runBlocking {
        val s = session()
        s.login("alice", "pw")
        assertEquals("alice", s.user.value)
        assertEquals("sid-1", s.sessionId())
    }

    @Test
    fun concurrent401sShareOneRefreshAndAllSucceed() = runBlocking {
        val store = InMemoryTokenStore(Tokens(jwt("alice", "sid-1", far(), nonce = -1), "r-old"))
        val s = session(store)
        val results = withContext(Dispatchers.IO) {
            (1..8).map { async { s.authorized(ApiRequest("GET", "/v2/shopee/orders")).code } }.awaitAll()
        }
        assertEquals(List(8) { 200 }, results)
        assertEquals(1, refreshes.get())
    }

    @Test
    fun rejectedRefreshLogsOutAndReports() = runBlocking {
        refreshAllowed = false
        val store = InMemoryTokenStore(Tokens(jwt("alice", "sid-1", far(), nonce = -1), "r-old"))
        val s = session(store)
        try {
            s.authorized(ApiRequest("GET", "/v2/shopee/orders"))
            fail("expected logout")
        } catch (e: NotLoggedInException) {
            assertNull(store.load())
        }
        assertTrue(AppEvent.LoggedOut in events)
        assertNull(s.user.value)
    }

    @Test
    fun accessTokenAboutToExpireIsRefreshedBeforeTheCall() = runBlocking {
        val store = InMemoryTokenStore(Tokens(jwt("alice", "sid-1", System.currentTimeMillis() / 1000 + 10), "r-old"))
        val s = session(store)
        assertEquals(200, s.authorized(ApiRequest("GET", "/v2/shopee/orders")).code)
        assertEquals(1, refreshes.get())
        assertEquals(1, server.requestCount - 1) // the refresh, then one call without a 401
    }

    @Test
    fun logoutClearsLocallyEvenWhenTheServerIsDown() = runBlocking {
        val store = InMemoryTokenStore(Tokens(validAccess, "r"))
        val s = session(store)
        server.shutdown()
        s.logout()
        assertNull(store.load())
        Unit
    }

    companion object {
        fun far() = System.currentTimeMillis() / 1000 + 3600

        fun jwt(sub: String, sid: String, exp: Long, nonce: Int = 0): String {
            val enc = Base64.getUrlEncoder().withoutPadding()
            val header = enc.encodeToString("""{"alg":"none"}""".toByteArray())
            val payload = enc.encodeToString("""{"sub":"$sub","sid":"$sid","exp":$exp,"n":$nonce}""".toByteArray())
            return "$header.$payload.sig"
        }
    }
}
