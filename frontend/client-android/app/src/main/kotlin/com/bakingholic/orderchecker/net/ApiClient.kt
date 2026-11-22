package com.bakingholic.orderchecker.net

import com.bakingholic.orderchecker.core.AppInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import kotlin.coroutines.CoroutineContext

/** One HTTP call to the backend, independent of the address it goes to. */
data class ApiRequest(
    val method: String,
    val path: String,
    val query: Map<String, String> = emptyMap(),
    val jsonBody: String? = null,
)

/** Raw answer: status and body text. */
data class ApiResponse(val code: Int, val body: String, val address: String) {
    val isSuccessful: Boolean get() = code in 200..299
}

/**
 * Sends requests to the active address of the profile, switching on connection failures
 * ([AddressSelector]). Adds `X-Client-Version` and the optional `CF-Access-*` headers to every
 * request. Query values are URL-encoded by [HttpUrl.Builder]. A 426 raises
 * [UpgradeRequiredException] and is reported through [onEvent].
 */
class ApiClient(
    private val http: OkHttpClient,
    private val appInfo: AppInfo,
    private val profile: () -> ServerProfile,
    val selector: AddressSelector,
    private val onEvent: (AppEvent) -> Unit = {},
    private val io: CoroutineContext = Dispatchers.IO,
) {
    private val json = Json { ignoreUnknownKeys = true }

    fun url(address: String, request: ApiRequest): HttpUrl {
        val builder = (address.trimEnd('/') + request.path).toHttpUrl().newBuilder()
        request.query.forEach { (k, v) -> builder.addQueryParameter(k, v) }
        return builder.build()
    }

    /** Send [request] with an optional bearer token; never refreshes (see [AuthorizedApi]). */
    suspend fun send(request: ApiRequest, bearer: String? = null): ApiResponse =
        withContext(io) {
            val current = profile()
            selector.update(current)
            var lastError: Throwable? = null
            for (address in selector.order()) {
                val response: Response =
                    try {
                        http.newCall(build(address, request, bearer, current)).execute()
                    } catch (e: Exception) {
                        if (!ConnectionFailure.isFailure(e)) throw e
                        lastError = e
                        selector.connectionFailed(address)
                        continue
                    }
                response.use {
                    if (ConnectionFailure.isFailure(it)) {
                        lastError = ApiException(it.code, null)
                        selector.connectionFailed(address)
                        return@use null
                    }
                    selector.answered(address)
                    ApiResponse(it.code, it.body.string(), address)
                }?.let { answer ->
                    if (answer.code == 426) {
                        val min = minSupported(answer.body)
                        onEvent(AppEvent.UpgradeRequired(min))
                        throw UpgradeRequiredException(min)
                    }
                    return@withContext answer
                }
            }
            throw ServerUnreachableException(lastError)
        }

    /** Try the primary when on the fallback and a probe is due; moves back if it answers. */
    suspend fun probePrimaryIfDue() {
        if (!selector.primaryProbeDue()) return
        val primary = selector.primary() ?: return
        withContext(io) {
            runCatching {
                http.newCall(build(primary, ApiRequest("GET", "/v2/meta"), null, profile())).execute().use {
                    if (!ConnectionFailure.isFailure(it)) selector.answered(primary)
                }
            }
        }
    }

    private fun build(address: String, request: ApiRequest, bearer: String?, current: ServerProfile): Request {
        val body = request.jsonBody?.toRequestBody(JSON)
            ?: if (request.method == "POST") "".toRequestBody(JSON) else null
        val builder = Request.Builder()
            .url(url(address, request))
            .method(request.method, body)
            .header("X-Client-Version", appInfo.clientVersionHeader)
            .header("Accept", "application/json")
        current.accessHeaders.forEach { (k, v) -> builder.header(k, v) }
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        return builder.build()
    }

    private fun minSupported(body: String): Int? =
        runCatching { json.parseToJsonElement(body).jsonObject["min_supported_version_code"]?.jsonPrimitive?.intOrNull }
            .getOrNull()

    fun detail(body: String): String? =
        runCatching { json.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.contentOrNull }.getOrNull()

    companion object {
        val JSON = "application/json".toMediaType()
    }
}
