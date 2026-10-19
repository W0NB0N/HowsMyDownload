package com.notifs.app.service

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.notifs.app.data.PairingApi
import com.notifs.app.data.PairingDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

class NotifFcmService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "NotifFcmService"
        // Rendering runs in coroutines: serialize the seq check + save + render so two pushes
        // can never interleave or both pass the gate.
        private val messageMutex = Mutex()
        private val finishedDownloadIds = java.util.Collections.synchronizedSet(mutableSetOf<String>())
        @Volatile
        private var safetyNetJob: Job? = null

        fun resetState() {
            finishedDownloadIds.clear()
            safetyNetJob?.cancel()
            safetyNetJob = null
        }
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var notificationHelper: NotificationHelper
    private lateinit var dataStore: PairingDataStore

    override fun onCreate() {
        super.onCreate()
        notificationHelper = NotificationHelper(applicationContext)
        dataStore = PairingDataStore(applicationContext)
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.i(TAG, "New FCM token received")
        serviceScope.launch {
            dataStore.saveFcmToken(token)
            val pairingInfo = dataStore.getPairingInfo()
            val pairingId = pairingInfo.pairingId
            val serverUrl = pairingInfo.serverUrl
            val deviceSecret = dataStore.getDeviceSecret()
            if (pairingInfo.isPaired && !pairingId.isNullOrBlank() && !serverUrl.isNullOrBlank()) {
                if (deviceSecret.isNullOrBlank()) {
                    Log.w(TAG, "Paired without a device secret (pre-upgrade pairing); re-pair to sync token")
                    return@launch
                }
                try {
                    when (val code = PairingApi.refreshToken(serverUrl, pairingId, deviceSecret, token)) {
                        200 -> Log.i(TAG, "Refreshed FCM token on server for pairing: $pairingId")
                        401 -> Log.w(TAG, "Server rejected device secret (pairing gone); token not updated")
                        else -> Log.w(TAG, "Server rejected token refresh: HTTP $code")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to refresh token on server: ${e.message}")
                }
            }
        }
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        val data = remoteMessage.data
        if (data.isEmpty()) {
            Log.w(TAG, "Received empty FCM data payload")
            return
        }


        // Check for server-initiated or extension-initiated unpair event
        if (data["event"] == "unpaired") {
            val unpairId = data["pairing_id"] ?: ""
            serviceScope.launch {
                val currentId = dataStore.getPairingInfo().pairingId
                if (!currentId.isNullOrBlank() && unpairId != currentId) {
                    // A late unpair for a previous pairing must not tear down the current one
                    Log.w(TAG, "Ignoring unpair event for '$unpairId' (current pairing is '$currentId')")
                    return@launch
                }
                Log.i(TAG, "Unpair event received via FCM for pairing_id='$unpairId'. Clearing pairing state.")
                dataStore.clearPairing()
                resetState()
                notificationHelper.cancelAll()
            }
            return
        }

        val seq = data["seq"]?.toIntOrNull() ?: 0
        val epoch = data["epoch"]?.toLongOrNull() ?: 0L
        // >0 when the server trimmed the list to fit FCM's 4KB limit
        val omitted = data["omitted"]?.toIntOrNull() ?: 0
        val pairingId = data["pairing_id"] ?: ""
        val source = data["source"] ?: "Chrome"
        val pcName = data["pc_name"] ?: "Desktop-PC"
        val downloadsJsonStr = data["downloads"] ?: "[]"

        serviceScope.launch { messageMutex.withLock {
            val hideFilenames = dataStore.getHideFilenames()
            val incoming = StreamPosition(epoch = epoch, seq = seq)
            val last = dataStore.getStreamPosition()

            when (val decision = SequenceGate.evaluate(dataStore.getPairingInfo().pairingId, pairingId, last, incoming)) {
                is SequenceGate.Decision.Drop -> {
                    Log.d(TAG, "Dropping push: ${decision.reason}")
                    return@withLock
                }
                SequenceGate.Decision.Accept -> {
                    if (last != null && last.epoch != incoming.epoch) {
                        Log.i(TAG, "Server restarted (epoch ${last.epoch} -> ${incoming.epoch}); new seq stream")
                    }
                    if (seq > 0) dataStore.saveStreamPosition(incoming)
                }
            }

            try {
                val encKey = dataStore.getEncryptionKey()
                val jsonArray = JSONArray(downloadsJsonStr)
                val uiDownloads = mutableListOf<com.notifs.app.data.AppDownloadItem>()

                data class ActiveCandidate(
                    val id: String,
                    val filename: String,
                    val state: String,
                    val pct: Float?,
                    val speed: Long,
                    val eta: Long?,
                    val bytesDownloaded: Long,
                    val totalBytes: Long?
                )
                val activeCandidates = mutableListOf<ActiveCandidate>()
                var totalSpeedBytes: Long = 0

                for (i in 0 until jsonArray.length()) {
                    val item: JSONObject = jsonArray.getJSONObject(i)
                    val id = item.getString("id")
                    val rawFilename = item.getString("filename")
                    val filename = com.notifs.app.util.CryptoUtils.decryptFilename(rawFilename, encKey)
                    val state = item.getString("state").lowercase()
                    val pct = if (item.has("percentage") && !item.isNull("percentage")) {
                        item.getDouble("percentage").toFloat()
                    } else {
                        null
                    }
                    val speed = if (item.has("speed")) item.getLong("speed") else 0L
                    val eta = if (item.has("eta_seconds") && !item.isNull("eta_seconds")) {
                        item.getLong("eta_seconds")
                    } else {
                        null
                    }
                    val bytesDownloaded = if (item.has("bytes_downloaded")) item.getLong("bytes_downloaded") else 0L
                    val totalBytes = if (item.has("total_bytes") && !item.isNull("total_bytes")) {
                        item.getLong("total_bytes")
                    } else {
                        null
                    }

                    if (state != "erased") {
                        uiDownloads.add(
                            com.notifs.app.data.AppDownloadItem(
                                id = id,
                                filename = filename,
                                state = state,
                                bytesDownloaded = bytesDownloaded,
                                totalBytes = totalBytes,
                                percentage = pct,
                                speedBytesSec = speed,
                                etaSeconds = eta
                            )
                        )
                    }

                    when (state) {
                        "completed" -> {
                            dataStore.clearDismissedDownload(id)
                            if (finishedDownloadIds.add(id)) {
                                notificationHelper.showCompletionNotification(
                                    downloadId = id,
                                    filename = filename,
                                    success = true,
                                    source = source,
                                    pcName = pcName,
                                    hideFilenames = hideFilenames
                                )
                            }
                        }
                        "failed" -> {
                            dataStore.clearDismissedDownload(id)
                            if (finishedDownloadIds.add(id)) {
                                notificationHelper.showCompletionNotification(
                                    downloadId = id,
                                    filename = filename,
                                    success = false,
                                    source = source,
                                    pcName = pcName,
                                    hideFilenames = hideFilenames
                                )
                            }
                        }
                        "erased" -> {
                            finishedDownloadIds.remove(id)
                            dataStore.clearDismissedDownload(id)
                            notificationHelper.cancelNotification(id)
                        }
                        "paused", "starting", "downloading" -> {
                            finishedDownloadIds.remove(id)
                            // Check if user swiped away this download notification
                            if (!dataStore.isDownloadDismissed(id)) {
                                if (state != "paused") {
                                    totalSpeedBytes += speed
                                }
                                activeCandidates.add(
                                    ActiveCandidate(
                                        id = id,
                                        filename = filename,
                                        state = state,
                                        pct = pct,
                                        speed = speed,
                                        eta = eta,
                                        bytesDownloaded = bytesDownloaded,
                                        totalBytes = totalBytes
                                    )
                                )
                            }
                        }
                    }
                }

                // Clean up any progress notifications that are no longer active. Skipped when the
                // server trimmed the payload: absent downloads may still be running.
                if (omitted == 0) {
                    val currentActiveIds = activeCandidates.map { it.id }.toSet()
                    notificationHelper.cleanRemovedProgressNotifications(currentActiveIds)
                } else {
                    Log.w(TAG, "Server omitted $omitted downloads to fit the FCM size limit")
                }

                // Calculate total remaining bytes across active downloads
                var totalRemainingBytes: Long = 0L
                var hasKnownRemaining = false
                for (active in activeCandidates) {
                    if (active.totalBytes != null && active.totalBytes > active.bytesDownloaded) {
                        totalRemainingBytes += (active.totalBytes - active.bytesDownloaded)
                        hasKnownRemaining = true
                    }
                }
                val remainingBytesParam = if (hasKnownRemaining) totalRemainingBytes else null

                // Group summary if multiple active downloads exist (3+ downloads): Post BEFORE child items
                if (activeCandidates.size >= 3) {
                    val summaryItems = activeCandidates.map { Pair(it.filename, it.pct) }
                    notificationHelper.showGroupSummary(
                        activeCount = activeCandidates.size,
                        totalSpeedBytes = totalSpeedBytes,
                        totalRemainingBytes = remainingBytesParam,
                        activeItems = summaryItems,
                        source = source,
                        pcName = pcName,
                        hideFilenames = hideFilenames
                    )
                } else {
                    notificationHelper.cancelGroupSummary()
                }

                // Show individual progress notifications for ALL active downloads
                for (active in activeCandidates) {
                    notificationHelper.showProgressNotification(
                        downloadId = active.id,
                        filename = active.filename,
                        percentage = active.pct,
                        speedBytesSec = active.speed,
                        etaSeconds = active.eta,
                        source = source,
                        pcName = pcName,
                        hideFilenames = hideFilenames,
                        state = active.state
                    )
                }

                // 90-second local safety net watchdog: only arm if transfers are ACTIVELY downloading (not paused)
                val hasActivelyTransferring = activeCandidates.any { it.state == "downloading" || it.state == "starting" }
                if (hasActivelyTransferring) {
                    safetyNetJob?.cancel()
                    safetyNetJob = serviceScope.launch {
                        delay(90_000L)
                        Log.w(TAG, "Local safety net triggered: 90s elapsed without FCM updates while transfers active")
                        notificationHelper.showStaleNotification(source = source, pcName = pcName)
                    }
                } else {
                    safetyNetJob?.cancel()
                    safetyNetJob = null
                }

                // Update active downloads for UI
                com.notifs.app.data.DownloadRepository.updateDownloads(uiDownloads)

            } catch (e: Exception) {
                // Never log the payload: it carries (encrypted) filenames and pairing metadata
                Log.e(TAG, "Error processing downloads payload (seq=$seq)", e)
            }
        } }
    }
}
