package com.bakingholic.orderchecker.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.bakingholic.orderchecker.net.ServerProfile
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

/** The server profile, kept in DataStore; [default] until someone edits it. */
class ProfileStore(private val dataStore: DataStore<Preferences>, private val default: ServerProfile) {
    private val key = stringPreferencesKey("server_profile")
    private val json = Json { ignoreUnknownKeys = true }

    val profile: Flow<ServerProfile> = dataStore.data.map { prefs ->
        prefs[key]?.let { runCatching { json.decodeFromString(ServerProfile.serializer(), it) }.getOrNull() } ?: default
    }

    suspend fun save(profile: ServerProfile) {
        require(profile.isValid()) { "Addresses must start with http:// or https://" }
        dataStore.edit { it[key] = json.encodeToString(ServerProfile.serializer(), profile) }
    }

    suspend fun reset() {
        dataStore.edit { it.remove(key) }
    }
}
