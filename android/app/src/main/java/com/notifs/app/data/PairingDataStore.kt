package com.notifs.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "notifs_preferences")

data class PairingInfo(
    val pairingId: String?,
    val serverUrl: String?,
    val pcName: String?,
    val isPaired: Boolean
)

class PairingDataStore(private val context: Context) {

    companion object {
        private val KEY_FCM_TOKEN = stringPreferencesKey("fcm_token")
        private val KEY_PAIRING_ID = stringPreferencesKey("pairing_id")
        private val KEY_SERVER_URL = stringPreferencesKey("server_url")
        private val KEY_PAIRED_PC_NAME = stringPreferencesKey("paired_pc_name")
        private val KEY_IS_PAIRED = booleanPreferencesKey("is_paired")
        private val KEY_LAST_SEQ = intPreferencesKey("last_seq")
        private val KEY_DISMISSED_IDS = stringPreferencesKey("dismissed_download_ids")
        private val KEY_HIDE_FILENAMES = booleanPreferencesKey("hide_filenames_in_notifs")
        private val KEY_LEGACY_HIDE_LOCK = booleanPreferencesKey("hide_filenames_lock_screen")
    }

    val fcmTokenFlow: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[KEY_FCM_TOKEN]
    }

    val pairingInfoFlow: Flow<PairingInfo> = context.dataStore.data.map { prefs ->
        PairingInfo(
            pairingId = prefs[KEY_PAIRING_ID],
            serverUrl = prefs[KEY_SERVER_URL],
            pcName = prefs[KEY_PAIRED_PC_NAME],
            isPaired = prefs[KEY_IS_PAIRED] ?: false
        )
    }

    val hideFilenamesFlow: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[KEY_HIDE_FILENAMES] ?: prefs[KEY_LEGACY_HIDE_LOCK] ?: false
    }

    val hideFilenamesLockScreenFlow: Flow<Boolean> = hideFilenamesFlow

    suspend fun setHideFilenames(hide: Boolean) {
        context.dataStore.edit { prefs ->
            prefs[KEY_HIDE_FILENAMES] = hide
            prefs[KEY_LEGACY_HIDE_LOCK] = hide
        }
    }

    suspend fun setHideFilenamesLockScreen(hide: Boolean) = setHideFilenames(hide)

    suspend fun getHideFilenames(): Boolean {
        return hideFilenamesFlow.first()
    }

    suspend fun getHideFilenamesLockScreen(): Boolean = getHideFilenames()

    suspend fun saveFcmToken(token: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_FCM_TOKEN] = token
        }
    }

    suspend fun getFcmToken(): String? {
        return context.dataStore.data.map { it[KEY_FCM_TOKEN] }.first()
    }

    suspend fun savePairing(pairingId: String, serverUrl: String, pcName: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_PAIRING_ID] = pairingId
            prefs[KEY_SERVER_URL] = serverUrl
            prefs[KEY_PAIRED_PC_NAME] = pcName
            prefs[KEY_IS_PAIRED] = true
            prefs[KEY_LAST_SEQ] = 0
        }
    }

    suspend fun clearPairing() {
        context.dataStore.edit { prefs ->
            prefs.remove(KEY_PAIRING_ID)
            prefs.remove(KEY_SERVER_URL)
            prefs.remove(KEY_PAIRED_PC_NAME)
            prefs[KEY_IS_PAIRED] = false
            prefs[KEY_LAST_SEQ] = 0
        }
    }

    suspend fun getPairingInfo(): PairingInfo {
        return pairingInfoFlow.first()
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
