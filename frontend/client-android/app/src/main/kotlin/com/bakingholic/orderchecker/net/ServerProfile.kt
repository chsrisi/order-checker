package com.bakingholic.orderchecker.net

import kotlinx.serialization.Serializable

/**
 * Where the backend is (V2_SERVER_ADDRESS §4.2). Stage 1 is the LAN address only; stage 2 adds
 * the domain as primary, the LAN as fallback, and a Cloudflare Access service token.
 */
@Serializable
data class ServerProfile(
    val primary: String,
    val fallback: String? = null,
    val accessClientId: String? = null,
    val accessClientSecret: String? = null,
) {
    val addresses: List<String> get() = listOfNotNull(primary, fallback).map { it.trimEnd('/') }.distinct()

    /** The `CF-Access-*` headers, only when both halves of the service token are set. */
    val accessHeaders: Map<String, String>
        get() =
            if (!accessClientId.isNullOrBlank() && !accessClientSecret.isNullOrBlank()) {
                mapOf("CF-Access-Client-Id" to accessClientId, "CF-Access-Client-Secret" to accessClientSecret)
            } else {
                emptyMap()
            }

    fun isValid(): Boolean = addresses.all { it.startsWith("http://") || it.startsWith("https://") }

    companion object {
        /** Stage 1: the LAN server, no fallback, no service token. */
        const val STAGE1_PRIMARY = "http://192.168.1.50:8000"
    }
}
