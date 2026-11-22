package com.bakingholic.orderchecker.auth

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** Round trip through AES-GCM and DataStore; a software key stands in for the Keystore. */
class TokenStoreTest {
    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test
    fun roundTripAndClear() = runBlocking {
        val dir = Files.createTempDirectory("tokens").toFile()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val dataStore = PreferenceDataStoreFactory.create(scope = scope) { File(dir, "secure.preferences_pb") }
        val store = EncryptedTokenStore(dataStore, AesGcmBox { key })
        val tokens = Tokens("access.jwt.value", "refresh.jwt.value")
        store.save(tokens)
        assertEquals(tokens, store.load())
        val raw = dataStore.data.first().asMap().values.single().toString()
        assertFalse("stored in clear text", raw.contains("refresh.jwt.value"))
        store.clear()
        assertNull(store.load())
        scope.cancel()
    }

    @Test
    fun aDifferentKeyCannotReadTheTokens() = runBlocking {
        val dir = Files.createTempDirectory("tokens").toFile()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val dataStore = PreferenceDataStoreFactory.create(scope = scope) { File(dir, "secure.preferences_pb") }
        EncryptedTokenStore(dataStore, AesGcmBox { key }).save(Tokens("a", "r"))
        val otherKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        assertNull(EncryptedTokenStore(dataStore, AesGcmBox { otherKey }).load())
        scope.cancel()
    }

    @Test
    fun claimsAreReadWithoutVerification() {
        val jwt = SessionManagerTest.jwt("alice", "sid-9", 1_000)
        val claims = AccessClaims.parse(jwt)
        assertEquals("alice", claims.subject)
        assertEquals("sid-9", claims.sessionId)
        assertEquals(true, claims.expiresWithin(60, 950))
        assertEquals(false, claims.expiresWithin(60, 900))
        assertNull(AccessClaims.parse("garbage").subject)
    }
}
