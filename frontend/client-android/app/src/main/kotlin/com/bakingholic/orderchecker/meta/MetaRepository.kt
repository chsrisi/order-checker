package com.bakingholic.orderchecker.meta

import com.bakingholic.orderchecker.api.model.MetaResponse
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ApiRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.Json

/** `/v2/meta`: contract range and the stock location mode (single/multi bin UX). */
class MetaRepository(private val api: ApiClient) {
    private val json = Json { ignoreUnknownKeys = true }
    private val _meta = MutableStateFlow<MetaResponse?>(null)
    val meta: StateFlow<MetaResponse?> = _meta

    suspend fun refresh(): MetaResponse? {
        val response = api.send(ApiRequest("GET", "/v2/meta"))
        if (!response.isSuccessful) return null
        return json.decodeFromString(MetaResponse.serializer(), response.body).also { _meta.value = it }
    }

    fun serverSupportsApp(meta: MetaResponse): Boolean =
        AppInfo.supportsServer(meta.clientContract.min, meta.clientContract.max)
}
