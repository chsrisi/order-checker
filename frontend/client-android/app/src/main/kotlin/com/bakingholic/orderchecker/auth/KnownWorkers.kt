package com.bakingholic.orderchecker.auth

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * Usernames that have logged in on this device, most recent first, for the login picker.
 * Names only, and kept across logout. They never come from the server, so nobody can list
 * accounts without logging in (F-M17).
 */
class KnownWorkers(private val dataStore: DataStore<Preferences>) {
    private val key = stringPreferencesKey("known_workers")
    private val serializer = ListSerializer(String.serializer())

    val names: Flow<List<String>> = dataStore.data.map { read(it) }

    suspend fun remember(username: String) {
        dataStore.edit { prefs ->
            val names = (listOf(username) + read(prefs)).distinct().take(MAX)
            prefs[key] = Json.encodeToString(serializer, names)
        }
    }

    private fun read(prefs: Preferences): List<String> =
        prefs[key]?.let { runCatching { Json.decodeFromString(serializer, it) }.getOrNull() }.orEmpty()

    companion object {
        const val MAX = 20
    }
}
