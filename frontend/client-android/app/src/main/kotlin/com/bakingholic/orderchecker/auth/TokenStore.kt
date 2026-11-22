package com.bakingholic.orderchecker.auth

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.Json

interface TokenStore {
    suspend fun load(): Tokens?

    suspend fun save(tokens: Tokens)

    suspend fun clear()
}

/** AES-GCM with a key from [key]; the IV is generated per message and stored in front. */
class AesGcmBox(private val key: () -> SecretKey) {
    fun seal(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val iv = cipher.iv
        return byteArrayOf(iv.size.toByte()) + iv + cipher.doFinal(plain)
    }

    fun open(sealed: ByteArray): ByteArray {
        val ivLength = sealed[0].toInt()
        val iv = sealed.copyOfRange(1, 1 + ivLength)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(sealed, 1 + ivLength, sealed.size - 1 - ivLength)
    }

    companion object {
        private const val TRANSFORMATION = "AES/GCM/NoPadding"

        /** A non-exportable AES-256 key in the Android Keystore, created on first use. */
        fun keystoreKey(alias: String): () -> SecretKey = {
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (keyStore.getKey(alias, null) as? SecretKey) ?: KeyGenerator
                .getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
                .apply {
                    init(
                        KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                            .setKeySize(256)
                            .build(),
                    )
                }.generateKey()
        }
    }
}

/** Tokens encrypted with [box] and kept in a preferences DataStore. */
class EncryptedTokenStore(
    private val dataStore: DataStore<Preferences>,
    private val box: AesGcmBox,
) : TokenStore {
    private val key = stringPreferencesKey("tokens")
    private val json = Json

    override suspend fun load(): Tokens? {
        val stored = dataStore.data.first()[key] ?: return null
        return runCatching {
            json.decodeFromString(Tokens.serializer(), String(box.open(Base64.getDecoder().decode(stored))))
        }.getOrNull() // unreadable (key lost after a restore): treated as logged out
    }

    override suspend fun save(tokens: Tokens) {
        val sealed = box.seal(json.encodeToString(Tokens.serializer(), tokens).toByteArray())
        dataStore.edit { it[key] = Base64.getEncoder().encodeToString(sealed) }
    }

    override suspend fun clear() {
        dataStore.edit { it.remove(key) }
    }
}

class InMemoryTokenStore(private var tokens: Tokens? = null) : TokenStore {
    override suspend fun load(): Tokens? = tokens

    override suspend fun save(tokens: Tokens) {
        this.tokens = tokens
    }

    override suspend fun clear() {
        tokens = null
    }
}
