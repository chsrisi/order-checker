package com.bakingholic.orderchecker.updater

import com.bakingholic.orderchecker.api.model.ClientReleaseResponse
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.ServerProfile
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import kotlin.coroutines.CoroutineContext

/** Result of asking the server for its newest release. */
sealed interface CheckResult {
    /** [address] answered; [release] is null when nothing is published (404). */
    data class Answered(val address: String, val release: ClientReleaseResponse?) : CheckResult

    /** No address answered (offline, server down): try again later, never crash. */
    data class Unreachable(val error: String?) : CheckResult
}

/**
 * Talks to the update endpoints. Independent of the login state (no token), and it tries
 * **every** address of the profile, so a broken primary never blocks an update (V2_SERVER_ADDRESS
 * §4.2).
 */
class UpdateChecker(
    private val http: OkHttpClient,
    private val appInfo: AppInfo,
    private val profile: () -> ServerProfile,
    private val io: CoroutineContext = Dispatchers.IO,
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun latest(): CheckResult = withContext(io) {
        var lastError: String? = null
        val current = profile()
        for (address in current.addresses) {
            try {
                http.newCall(request(address + "/v2/client/latest", current)).execute().use { response ->
                    when {
                        response.code == 404 -> return@withContext CheckResult.Answered(address, null)
                        response.isSuccessful -> return@withContext CheckResult.Answered(
                            address,
                            json.decodeFromString(ClientReleaseResponse.serializer(), response.body.string()),
                        )
                        else -> lastError = "HTTP ${response.code}"
                    }
                }
            } catch (e: IOException) {
                lastError = e.message ?: e.javaClass.simpleName
            } catch (e: IllegalArgumentException) {
                lastError = e.message // malformed address or body
            }
        }
        CheckResult.Unreachable(lastError)
    }

    /**
     * Download [release] from [address] into [target], hashing while writing. Returns the
     * SHA-256 hex of what was written. [onProgress] gets 0..1 when the size is known.
     */
    suspend fun download(
        address: String,
        release: ClientReleaseResponse,
        target: File,
        onProgress: (Float) -> Unit = {},
    ): String = withContext(io) {
        val url = address.toHttpUrl().resolve(release.apkUrl) ?: throw IOException("Bad apk_url")
        http.newCall(request(url.toString(), profile())).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Download failed: HTTP ${response.code}")
            target.parentFile?.mkdirs()
            val digest = MessageDigest.getInstance("SHA-256")
            val total = response.body.contentLength().takeIf { it > 0 } ?: release.sizeBytes?.toLong()
            var written = 0L
            response.body.byteStream().use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                        written += read
                        total?.let { onProgress((written.toFloat() / it).coerceIn(0f, 1f)) }
                    }
                }
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        }
    }

    private fun request(url: String, current: ServerProfile): Request {
        val builder = Request.Builder().url(url).header("X-Client-Version", appInfo.clientVersionHeader)
        current.accessHeaders.forEach { (k, v) -> builder.header(k, v) }
        return builder.build()
    }
}
