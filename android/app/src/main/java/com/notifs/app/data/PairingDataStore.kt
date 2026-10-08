package com.notifs.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "notifs_preferences")

class PairingDataStore(private val context: Context) {

    companion object {
        private val KEY_FCM_TOKEN = stringPreferencesKey("fcm_token")
        private val KEY_PAIRED_PC_NAME = stringPreferencesKey("paired_pc_name")
        private val KEY_LAST_SEQ = intPreferencesKey("last_seq")
        private val KEY_DISMISSED_IDS = stringPreferencesKey("dismissed_download_ids")
    }

    val fcmTokenFlow: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[KEY_FCM_TOKEN]
    }

    val pairedPcFlow: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[KEY_PAIRED_PC_NAME]
    }

    suspend fun saveFcmToken(token: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_FCM_TOKEN] = token
        }
    }

    suspend fun getFcmToken(): String? {
        return context.dataStore.data.map { it[KEY_FCM_TOKEN] }.first()
    }

    suspend fun saveLastSeq(seq: Int) {
        context.dataStore.edit { prefs ->
            prefs[KEY_LAST_SEQ] = seq
        }
    }

    suspend fun getLastSeq(): Int {
        return context.dataStore.data.map { it[KEY_LAST_SEQ] ?: 0 }.first()
    }

    suspend fun markDownloadDismissed(downloadId: String) {
        context.dataStore.edit { prefs ->
            val current = prefs[KEY_DISMISSED_IDS] ?: ""
            val set = current.split(",").filter { it.isNotBlank() }.toMutableSet()
            set.add(downloadId)
            prefs[KEY_DISMISSED_IDS] = set.joinToString(",")
        }
    }

    suspend fun isDownloadDismissed(downloadId: String): Boolean {
        val current = context.dataStore.data.map { it[KEY_DISMISSED_IDS] ?: "" }.first()
        return current.split(",").contains(downloadId)
    }

    suspend fun clearDismissedDownload(downloadId: String) {
        context.dataStore.edit { prefs ->
            val current = prefs[KEY_DISMISSED_IDS] ?: ""
            val set = current.split(",").filter { it.isNotBlank() && it != downloadId }.toSet()
            prefs[KEY_DISMISSED_IDS] = set.joinToString(",")
        }
    }
}
