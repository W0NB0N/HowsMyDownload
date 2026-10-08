package com.notifs.app.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.notifs.app.MainActivity
import com.notifs.app.R

class NotificationHelper(private val context: Context) {

    companion object {
        const val CHANNEL_DOWNLOADS = "downloads_v2"
        const val CHANNEL_COMPLETIONS = "completions_v2"
        const val GROUP_DOWNLOADS = "com.notifs.app.DOWNLOADS_GROUP"
        const val SUMMARY_ID = 0
        const val ACTION_DISMISSED = "com.notifs.app.ACTION_DISMISSED"
        const val EXTRA_DOWNLOAD_ID = "extra_download_id"

        private const val BRAND_COLOR = 0xFF8A05FF.toInt()
    }

    private val notificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    init {
        createChannels()
    }

    fun createChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // Delete legacy channels if they exist
            try {
                notificationManager.deleteNotificationChannel("downloads")
                notificationManager.deleteNotificationChannel("completions")
            } catch (_: Exception) {}

            // 1. Silent Active Progress Channel (Default importance for lockscreen & status bar visibility, but no sound/vibration)
            val downloadsChannel = NotificationChannel(
                CHANNEL_DOWNLOADS,
                "Active Downloads",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Live progress bar for in-progress transfers"
                setShowBadge(false)
                enableVibration(false)
                setSound(null, null)
                lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
            }

            // 2. Audible Completion Channel
            val completionsChannel = NotificationChannel(
                CHANNEL_COMPLETIONS,
                "Download Completed",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Alerts when a download finishes or fails"
                setShowBadge(true)
                enableVibration(true)
                lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
            }

            notificationManager.createNotificationChannel(downloadsChannel)
            notificationManager.createNotificationChannel(completionsChannel)
        }
    }

    private fun getNotificationId(downloadId: String): Int {
        // Consistent positive notification ID based on downloadId hash
        return (downloadId.hashCode() and 0x7FFFFFFF) + 1000
    }

    fun showProgressNotification(
        downloadId: String,
        filename: String,
        percentage: Float?,
        speedBytesSec: Long,
        etaSeconds: Long?,
        source: String = "Chrome",
        pcName: String = "Desktop-PC"
    ) {
        val notifId = getNotificationId(downloadId)
        val isIndeterminate = (percentage == null)
        val pctInt = percentage?.toInt() ?: 0

        val speedStr = formatSpeed(speedBytesSec)
        val etaStr = formatEta(etaSeconds)
        val pctStr = if (percentage != null) "${String.format("%.1f", percentage)}%" else "LIVE"

        // Format: "42.0% · 5.2 MB/s · 3m left"
        val contentText = if (etaStr.isNotBlank()) {
            "$pctStr · $speedStr · $etaStr"
        } else {
            "$pctStr · $speedStr"
        }
        val subText = "${source.replaceFirstChar { it.uppercase() }} · $pcName"

        val openIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingOpenIntent = PendingIntent.getActivity(
            context,
            notifId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Delete intent when user swipes away
        val deleteIntent = Intent(context, NotificationDismissReceiver::class.java).apply {
            action = ACTION_DISMISSED
            putExtra(EXTRA_DOWNLOAD_ID, downloadId)
        }
        val pendingDeleteIntent = PendingIntent.getBroadcast(
            context,
            notifId,
            deleteIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(context, CHANNEL_DOWNLOADS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle(filename)
            .setContentText(contentText)
            .setSubText(subText)
            .setContentIntent(pendingOpenIntent)
            .setDeleteIntent(pendingDeleteIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setGroup(GROUP_DOWNLOADS)
            .setProgress(100, pctInt, isIndeterminate)

        notificationManager.notify(notifId, builder.build())
    }

    fun showCompletionNotification(
        downloadId: String,
        filename: String,
        success: Boolean,
        source: String = "Chrome",
        pcName: String = "Desktop-PC"
    ) {
        val notifId = getNotificationId(downloadId)

        // Cancel the ongoing progress notification
        notificationManager.cancel(notifId)

        val title = if (success) "Download Complete" else "Download Failed"
        val subText = "${source.replaceFirstChar { it.uppercase() }} · $pcName"

        val openIntent = Intent(context, MainActivity::class.java)
        val pendingOpenIntent = PendingIntent.getActivity(
            context,
            notifId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(context, CHANNEL_COMPLETIONS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle(title)
            .setContentText(filename)
            .setSubText(subText)
            .setContentIntent(pendingOpenIntent)
            .setAutoCancel(true)
            .setOngoing(false)
            .setCategory(if (success) NotificationCompat.CATEGORY_STATUS else NotificationCompat.CATEGORY_ERROR)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)

        notificationManager.notify(notifId, builder.build())
    }

    fun cancelNotification(downloadId: String) {
        notificationManager.cancel(getNotificationId(downloadId))
    }

    fun showGroupSummary(activeCount: Int, totalSpeedBytes: Long, pcName: String = "Desktop-PC") {
        if (activeCount <= 1) {
            notificationManager.cancel(SUMMARY_ID)
            return
        }

        val speedStr = formatSpeed(totalSpeedBytes)
        val summaryText = "$activeCount downloads · $speedStr"

        val summaryBuilder = NotificationCompat.Builder(context, CHANNEL_DOWNLOADS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle(summaryText)
            .setSubText(pcName)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setGroup(GROUP_DOWNLOADS)
            .setGroupSummary(true)

        notificationManager.notify(SUMMARY_ID, summaryBuilder.build())
    }

    private fun formatSpeed(bytesPerSec: Long): String {
        if (bytesPerSec >= 1024 * 1024) {
            return String.format("%.1f MB/s", bytesPerSec / (1024.0 * 1024.0))
        }
        if (bytesPerSec >= 1024) {
            return String.format("%.0f KB/s", bytesPerSec / 1024.0)
        }
        return "$bytesPerSec B/s"
    }

    private fun formatEta(seconds: Long?): String {
        if (seconds == null || seconds < 0) return ""
        if (seconds == 0L) return "Done"
        if (seconds >= 3600) {
            val h = seconds / 3600
            val m = (seconds % 3600) / 60
            return "${h}h ${m}m left"
        }
        if (seconds >= 60) {
            val m = seconds / 60
            val s = seconds % 60
            return "${m}m ${s}s left"
        }
        return "${seconds}s left"
    }
}
