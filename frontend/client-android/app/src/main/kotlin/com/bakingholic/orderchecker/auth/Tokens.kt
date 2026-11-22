package com.bakingholic.orderchecker.auth

import java.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

@Serializable
data class Tokens(val access: String, val refresh: String)

/**
 * The claims the app reads from its own access token, without verifying it (Q11: the server
 * verifies; the app only refreshes early and shows who is logged in).
 */
data class AccessClaims(val subject: String?, val sessionId: String?, val expiresAtEpochSeconds: Long?) {
    fun expiresWithin(seconds: Long, nowEpochSeconds: Long): Boolean =
        expiresAtEpochSeconds != null && expiresAtEpochSeconds - nowEpochSeconds <= seconds

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(jwt: String): AccessClaims {
            val parts = jwt.split('.')
            if (parts.size < 2) return AccessClaims(null, null, null)
            return runCatching {
                val payload = String(Base64.getUrlDecoder().decode(parts[1].padBase64()))
                val obj = json.parseToJsonElement(payload).jsonObject
                AccessClaims(
                    subject = obj["sub"]?.jsonPrimitive?.contentOrNull,
                    sessionId = obj["sid"]?.jsonPrimitive?.contentOrNull,
                    expiresAtEpochSeconds = obj["exp"]?.jsonPrimitive?.longOrNull,
                )
            }.getOrDefault(AccessClaims(null, null, null))
        }

        private fun String.padBase64(): String = this + "=".repeat((4 - length % 4) % 4)
    }
}
