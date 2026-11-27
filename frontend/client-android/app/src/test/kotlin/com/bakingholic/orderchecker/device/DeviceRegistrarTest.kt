package com.bakingholic.orderchecker.device

import com.bakingholic.orderchecker.auth.InMemoryTokenStore
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.auth.SessionManagerTest
import com.bakingholic.orderchecker.auth.Tokens
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.AppEvent
import com.bakingholic.orderchecker.net.ServerProfile
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** A software P-256 key standing in for the Keystore one. */
class SoftwareDeviceKeys : DeviceKeys {
    val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

    override fun publicKeyBase64(): String = Base64.getEncoder().encodeToString(pair.public.encoded)

    override fun sign(data: ByteArray): ByteArray =
        Signature.getInstance("SHA256withECDSA").run { initSign(pair.private); update(data); sign() }
}

class MemoryRegistrationStore : RegistrationStore {
    var record: RegistrationRecord? = null

    override suspend fun load() = record

    override suspend fun save(record: RegistrationRecord) {
        this.record = record
    }
}

class DeviceRegistrarTest {
    private lateinit var server: MockWebServer
    private val keys = SoftwareDeviceKeys()
    private val store = MemoryRegistrationStore()
    private val access = SessionManagerTest.jwt("alice", "sid-42", SessionManagerTest.far())

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() = server.shutdown()

    private val tokens = InMemoryTokenStore(Tokens(access, "r"))
    private val events = mutableListOf<AppEvent>()

    private fun registrar(): DeviceRegistrar {
        val profile = ServerProfile(server.url("/").toString().trimEnd('/'))
        val api = ApiClient(OkHttpClient(), AppInfo(5, "2.0.4"), { profile }, AddressSelector())
        val session = SessionManager(api, tokens, onEvent = { events += it })
        return DeviceRegistrar(session, keys, AppInfo(5, "2.0.4"), "Newland MT67", "11", store)
    }

    private val deviceJson = """{"id":"dev-1","status":"pending","enrolled_at":"2026-11-22T10:00:00"}"""

    @Test
    fun signaturePayloadIsTheSessionIdVerifiableWithThePublicKey() {
        val body = registrar().requestFor("sid-42")
        val verifier = Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(keys.pair.public)
        verifier.update("sid-42".toByteArray())
        assertTrue(verifier.verify(Base64.getDecoder().decode(body.signature)))
        assertEquals(keys.publicKeyBase64(), body.publicKey)
        assertEquals(5, body.appVersionCode)
        assertEquals("Newland MT67", body.model)
    }

    @Test
    fun registersWithTheCurrentSidAndRemembersIt() = runBlocking {
        server.enqueue(MockResponse().setBody(deviceJson))
        val r = registrar()
        assertTrue(r.registerOnce())
        val sent = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
        assertEquals("11", sent["android_version"]!!.jsonPrimitive.content)
        assertEquals(DeviceStatus.Registered("dev-1", "pending"), r.status.value)
        assertEquals("sid-42", store.record!!.sessionId)
        // Same session again: no second request.
        assertTrue(r.registerOnce())
        assertEquals(1, server.requestCount)
    }

    @Test
    fun offlineIsRetriedAndTheRetryIsIdempotent() = runBlocking {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        server.enqueue(MockResponse().setResponseCode(503))
        server.enqueue(MockResponse().setBody(deviceJson))
        val r = registrar()
        assertFalse(r.registerOnce())
        assertTrue(r.status.value is DeviceStatus.Retrying)
        assertFalse(r.registerOnce())
        assertTrue(r.registerOnce())
        assertEquals(DeviceStatus.Registered("dev-1", "pending"), r.status.value)
        // Every attempt that reached the server carried the same key (same device row).
        val keysSent = (1..server.requestCount).mapNotNull {
            server.takeRequest().body.readUtf8().takeIf { b -> b.isNotEmpty() }
                ?.let { b -> Json.parseToJsonElement(b).jsonObject["public_key"]!!.jsonPrimitive.content }
        }.toSet()
        assertEquals(setOf(keys.publicKeyBase64()), keysSent)
    }

    @Test
    fun aRevokedDeviceStopsRetryingAndLogsOutLocally() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"Device revoked"}"""))
        val r = registrar()
        assertTrue(r.registerOnce())
        assertEquals(DeviceStatus.Revoked, r.status.value)
        // T8.1: the server ended the session too; the app clears it and says why.
        assertNull(tokens.load())
        assertEquals(listOf<AppEvent>(AppEvent.DeviceRevoked), events)
        assertEquals(1, server.requestCount) // no logout call for a session that is gone
    }
}
