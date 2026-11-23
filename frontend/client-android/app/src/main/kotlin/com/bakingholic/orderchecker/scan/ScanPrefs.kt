package com.bakingholic.orderchecker.scan

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Per-device scanner settings, changed in the hidden settings. */
class ScanPrefs(private val dataStore: DataStore<Preferences>) {
    private val suffixKey = stringPreferencesKey("scan_suffix")

    val suffix: Flow<ScanSuffix> = dataStore.data.map { ScanSuffix.parse(it[suffixKey]) }

    suspend fun setSuffix(suffix: ScanSuffix) {
        dataStore.edit { it[suffixKey] = suffix.name }
    }
}
