package com.bakingholic.orderchecker.api

import com.bakingholic.orderchecker.api.model.ClientReleaseResponse
import com.bakingholic.orderchecker.api.model.MetaResponse
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

/** The models generated from backend/openapi/v2.json parse what the backend sends (P-14). */
class GeneratedModelsTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesClientRelease() {
        val body = """{"version_code":3,"version_name":"2.0.2","apk_url":"/v2/client/apk/3",
            "sha256":"ab","size_bytes":10,"min_supported_version_code":2,"notes":null,
            "published_at":"2026-11-22T10:00:00Z","future_field":1}"""
        val release = json.decodeFromString(ClientReleaseResponse.serializer(), body)
        assertEquals(3, release.versionCode)
        assertEquals(2, release.minSupportedVersionCode)
    }

    @Test
    fun parsesMeta() {
        val body = """{"api_version":"0.6.0","client_contract":{"min":1,"max":2},
            "app_env":"production","stock_location_mode":"multi","features":{}}"""
        val meta = json.decodeFromString(MetaResponse.serializer(), body)
        assertEquals(2, meta.clientContract.max)
    }
}
