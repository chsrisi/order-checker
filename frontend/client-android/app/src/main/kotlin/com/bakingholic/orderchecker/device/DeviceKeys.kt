package com.bakingholic.orderchecker.device

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

/** The device's identity key (V2_SPEC §4A.1): EC P-256, signing only. */
interface DeviceKeys {
    /** Base64 DER SubjectPublicKeyInfo, as `POST /v2/device/register` expects. */
    fun publicKeyBase64(): String

    /** DER ECDSA signature with SHA-256. */
    fun sign(data: ByteArray): ByteArray
}

/** Non-exportable key pair in the Android Keystore, created on first use and kept forever. */
class KeystoreDeviceKeys(private val alias: String = "oc_device") : DeviceKeys {
    private val keyStore: KeyStore get() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    @Synchronized
    private fun ensure(): KeyStore {
        val ks = keyStore
        if (!ks.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(
                    KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                        .setDigests(KeyProperties.DIGEST_SHA256)
                        .build(),
                )
            }.generateKeyPair()
        }
        return ks
    }

    override fun publicKeyBase64(): String =
        Base64.getEncoder().encodeToString(ensure().getCertificate(alias).publicKey.encoded)

    override fun sign(data: ByteArray): ByteArray {
        val key = ensure().getKey(alias, null) as PrivateKey
        return Signature.getInstance("SHA256withECDSA").run {
            initSign(key)
            update(data)
            sign()
        }
    }
}
