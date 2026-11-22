package com.bakingholic.orderchecker.device

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.Json

class DataStoreRegistrationStore(private val dataStore: DataStore<Preferences>) : RegistrationStore {
    private val key = stringPreferencesKey("device_registration")

    override suspend fun load(): RegistrationRecord? =
        dataStore.data.first()[key]?.let { runCatching { Json.decodeFromString(RegistrationRecord.serializer(), it) }.getOrNull() }

    override suspend fun save(record: RegistrationRecord) {
        dataStore.edit { it[key] = Json.encodeToString(RegistrationRecord.serializer(), record) }
    }
}
