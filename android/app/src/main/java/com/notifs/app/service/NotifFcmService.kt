package com.notifs.app.service

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.notifs.app.data.PairingDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

class NotifFcmService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "NotifFcmService"
        @Volatile
        private var lastPairingId: String? = null
        @Volatile
        private var lastSeq: Int = 0
        @Volatile
        private var lastMessageTime: Long = 0L
        private val finishedDownloadIds = java.util.Collections.synchronizedSet(mutableSetOf<String>())

        fun resetState() {
            lastPairingId = null
            lastSeq = 0
            lastMessageTime = 0L
            finishedDownloadIds.clear()
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

        val seqStr = data["seq"] ?: "0"
        val seq = seqStr.toIntOrNull() ?: 0
        val pairingId = data["pairing_id"] ?: ""
        val source = data["source"] ?: "Chrome"
        val pcName = data["pc_name"] ?: "Desktop-PC"
        val downloadsJsonStr = data["downloads"] ?: "[]"

        val now = System.currentTimeMillis()

        // 1. If pairing_id changed, reset sequence and finished download cache immediately
        if (pairingId.isNotBlank() && pairingId != lastPairingId) {
            Log.i(TAG, "New pairing stream detected (old='$lastPairingId', new='$pairingId'). Resetting sequence tracking.")
            lastPairingId = pairingId
            lastSeq = 0
            finishedDownloadIds.clear()
        } else if (seq <= 1 || (now - lastMessageTime) > 15_000L || (lastSeq > 0 && seq < lastSeq - 5)) {
            // New download stream or timeout restart
            Log.d(TAG, "Stream reset: seq=$seq, lastSeq=$lastSeq")
            lastSeq = 0
            finishedDownloadIds.clear()
        }

        // 2. Drop out-of-order messages within the same active stream
        if (seq > 0 && lastSeq > 0 && seq < lastSeq) {
            Log.w(TAG, "Dropping out-of-order message: seq=$seq < lastSeq=$lastSeq")
            return
        }

        if (seq > 0) {
            lastSeq = seq
            lastMessageTime = now
        }

        serviceScope.launch {

            try {
                val jsonArray = JSONArray(downloadsJsonStr)
                var activeCount = 0
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

                    when (state) {
                        "completed" -> {
                            dataStore.clearDismissedDownload(id)
                            if (finishedDownloadIds.add(id)) {
                                notificationHelper.showCompletionNotification(
                                    downloadId = id,
                                    filename = filename,
                                    success = true,
                                    source = source,
                                    pcName = pcName
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
                                    pcName = pcName
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
                            // Check if user swiped away this download
                            if (!dataStore.isDownloadDismissed(id)) {
                                activeCount++
                                totalSpeedBytes += speed
                                notificationHelper.showProgressNotification(
                                    downloadId = id,
                                    filename = filename,
                                    percentage = pct,
                                    speedBytesSec = speed,
                                    etaSeconds = eta,
                                    source = source,
                                    pcName = pcName
                                )
                            }
                        }
                    }
                }

                // Update group summary if multi-download
                notificationHelper.showGroupSummary(activeCount, totalSpeedBytes, pcName)

            } catch (e: Exception) {
                Log.e(TAG, "Error parsing downloads JSON array: $downloadsJsonStr", e)
            }
        }
    }
}
