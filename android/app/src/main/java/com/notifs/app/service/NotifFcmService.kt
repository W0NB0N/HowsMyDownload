package com.notifs.app.service

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.notifs.app.data.PairingDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

class NotifFcmService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "NotifFcmService"
        @Volatile
        private var lastPairingId: String? = null
        private val finishedDownloadIds = java.util.Collections.synchronizedSet(mutableSetOf<String>())
        @Volatile
        private var safetyNetJob: Job? = null

        fun resetState() {
            lastPairingId = null
            finishedDownloadIds.clear()
            safetyNetJob?.cancel()
            safetyNetJob = null
        }
    }

    private val serviceScope = CoroutineScope(Dispatchers.IO)
    private lateinit var notificationHelper: NotificationHelper
    private lateinit var dataStore: PairingDataStore

    override fun onCreate() {
        super.onCreate()
        notificationHelper = NotificationHelper(applicationContext)
        dataStore = PairingDataStore(applicationContext)
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.i(TAG, "New FCM Token received: $token")
        serviceScope.launch {
            dataStore.saveFcmToken(token)
            val pairingInfo = dataStore.getPairingInfo()
            val pairingId = pairingInfo.pairingId
            val serverUrl = pairingInfo.serverUrl
            if (pairingInfo.isPaired && !pairingId.isNullOrBlank() && !serverUrl.isNullOrBlank()) {
                sendTokenRefresh(serverUrl, pairingId, token)
            }
        }
    }

    private fun sendTokenRefresh(serverUrl: String, pairingId: String, token: String) {
        try {
            val cleanUrl = serverUrl.trimEnd('/')
            val url = "$cleanUrl/v1/pairings/$pairingId/token"
            val json = JSONObject().apply {
                put("fcm_token", token)
            }
            val body = json.toString().toRequestBody("application/json; charset=utf-8".toMediaType())
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()

            val client = OkHttpClient()
            client.newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    Log.e(TAG, "Failed to refresh token on server: ${e.message}")
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (response.isSuccessful) {
                            Log.i(TAG, "Successfully refreshed FCM token on server for pairing: $pairingId")
                        } else {
                            Log.w(TAG, "Server rejected token refresh: HTTP ${response.code}")
                        }
                    }
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "Error initiating token refresh call", e)
        }
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        val data = remoteMessage.data
        if (data.isEmpty()) {
            Log.w(TAG, "Received empty FCM data payload")
            return
        }

        Log.d(TAG, "FCM data payload: $data")

        // Check for server-initiated or extension-initiated unpair event
        if (data["event"] == "unpaired") {
            val unpairId = data["pairing_id"] ?: ""
            Log.i(TAG, "Unpair event received via FCM for pairing_id='$unpairId'. Clearing pairing state.")
            serviceScope.launch {
                dataStore.clearPairing()
                resetState()
                notificationHelper.cancelAll()
            }
            return
        }

        val seqStr = data["seq"] ?: "0"
        val seq = seqStr.toIntOrNull() ?: 0
        val pairingId = data["pairing_id"] ?: ""
        val source = data["source"] ?: "Chrome"
        val pcName = data["pc_name"] ?: "Desktop-PC"
        val downloadsJsonStr = data["downloads"] ?: "[]"

        serviceScope.launch {
            val lastStoredSeq = dataStore.getLastSeq()
            val hideFilenames = dataStore.getHideFilenamesLockScreen()

            // 1. If pairing_id changed, reset sequence and finished download cache immediately
            if (pairingId.isNotBlank() && pairingId != lastPairingId) {
                Log.i(TAG, "New pairing stream detected (old='$lastPairingId', new='$pairingId'). Resetting sequence tracking.")
                lastPairingId = pairingId
                dataStore.saveLastSeq(seq)
                finishedDownloadIds.clear()
            } else {
                // Drop duplicate and out-of-order pushes (seq <= lastSeq)
                if (seq > 0 && lastStoredSeq > 0 && seq <= lastStoredSeq) {
                    Log.d(TAG, "Dropping duplicate or out-of-order message: seq=$seq <= lastSeq=$lastStoredSeq")
                    return@launch
                }
                if (seq > 0) {
                    dataStore.saveLastSeq(seq)
                }
            }

            try {
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
                    val filename = item.getString("filename")
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
                                    hideFilenamesOnLockScreen = hideFilenames
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
                                    hideFilenamesOnLockScreen = hideFilenames
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

                // Show individual progress notifications for ALL active downloads (no hard cap!)
                val currentActiveIds = activeCandidates.map { it.id }.toSet()
                for (active in activeCandidates) {
                    notificationHelper.showProgressNotification(
                        downloadId = active.id,
                        filename = active.filename,
                        percentage = active.pct,
                        speedBytesSec = active.speed,
                        etaSeconds = active.eta,
                        source = source,
                        pcName = pcName,
                        hideFilenamesOnLockScreen = hideFilenames,
                        state = active.state
                    )
                }

                // Clean up any progress notifications that are no longer active
                notificationHelper.cleanRemovedProgressNotifications(currentActiveIds)

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

                // Group summary if multiple active downloads exist (3+ downloads)
                val summaryItems = activeCandidates.map { Pair(it.filename, it.pct) }
                notificationHelper.showGroupSummary(
                    activeCount = activeCandidates.size,
                    totalSpeedBytes = totalSpeedBytes,
                    totalRemainingBytes = remainingBytesParam,
                    activeItems = summaryItems,
                    source = source,
                    pcName = pcName,
                    hideFilenamesOnLockScreen = hideFilenames
                )

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
                Log.e(TAG, "Error parsing downloads JSON array: $downloadsJsonStr", e)
            }
        }
    }
}
