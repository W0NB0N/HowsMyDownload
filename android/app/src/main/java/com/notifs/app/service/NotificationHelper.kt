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
import java.util.Locale

class NotificationHelper(private val context: Context) {

    companion object {
        const val CHANNEL_DOWNLOADS = "downloads_v3"
        const val CHANNEL_COMPLETIONS = "completions_v2"
        const val GROUP_DOWNLOADS = "com.notifs.app.DOWNLOADS_GROUP"
        const val SUMMARY_ID = 990
        const val ACTION_DISMISSED = "com.notifs.app.ACTION_DISMISSED"
        const val EXTRA_DOWNLOAD_ID = "extra_download_id"

        private const val BRAND_COLOR = 0xFF8A05FF.toInt()

        /**
         * OS-enforced backstop: a progress bar not refreshed within this window is removed by
         * the system even if this process is dead. Longer than the 90s watchdog so the
         * "PC offline" alert normally fires first.
         */
        const val PROGRESS_TIMEOUT_MS = 150_000L
        private const val STALE_NOTIFICATION_ID = 9999
    }

    private val notificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    /**
     * IDs of progress notifications currently in the shade, asked from the system rather than
     * kept in memory: an in-memory set was empty after process death, so "cancel all progress"
     * silently missed every bar posted by the previous process.
     */
    private fun activeProgressIds(): List<Int> =
        notificationManager.activeNotifications
            .filter { it.notification.channelId == CHANNEL_DOWNLOADS && it.id != SUMMARY_ID }
            .map { it.id }

    init {
        createChannels()
    }

    fun createChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // Delete legacy channels if they exist
            try {
                notificationManager.deleteNotificationChannel("downloads")
                notificationManager.deleteNotificationChannel("downloads_v2")
                notificationManager.deleteNotificationChannel("completions")
            } catch (_: Exception) {}

            // 1. Silent Active Progress Channel (Low importance for clean grouped progress bars without sound/vibration)
            val downloadsChannel = NotificationChannel(
                CHANNEL_DOWNLOADS,
                "Active Downloads",
                NotificationManager.IMPORTANCE_LOW
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
        pcName: String = "Desktop-PC",
        hideFilenames: Boolean = false,
        state: String = "downloading"
    ) {
        val notifId = getNotificationId(downloadId)

        val isIndeterminate = (percentage == null)
        val pctInt = percentage?.toInt() ?: 0

        val speedStr = formatSpeed(speedBytesSec)
        val etaStr = formatEta(etaSeconds)
        val pctStr = if (percentage != null) "${String.format(Locale.US, "%.1f", percentage)}%" else "LIVE"

        val isPaused = (state == "paused")
        val displayTitle = if (hideFilenames) {
            if (isPaused) "Download Paused" else "Downloading…"
        } else {
            filename
        }

        val contentText = when {
            isPaused -> "$pctStr · PAUSED"
            etaStr.isNotBlank() -> "$pctStr · $speedStr · $etaStr"
            else -> "$pctStr · $speedStr"
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
            .setContentTitle(displayTitle)
            .setContentText(contentText)
            .setSubText(subText)
            .setContentIntent(pendingOpenIntent)
            .setDeleteIntent(pendingDeleteIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setGroup(GROUP_DOWNLOADS)
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_SUMMARY)
            .setProgress(100, pctInt, isIndeterminate)
            .setTimeoutAfter(PROGRESS_TIMEOUT_MS)
            .setVisibility(if (hideFilenames) NotificationCompat.VISIBILITY_PRIVATE else NotificationCompat.VISIBILITY_PUBLIC)

        notificationManager.notify(notifId, builder.build())
    }

    fun showCompletionNotification(
        downloadId: String,
        filename: String,
        success: Boolean,
        source: String = "Chrome",
        pcName: String = "Desktop-PC",
        hideFilenames: Boolean = false
    ) {
        val notifId = getNotificationId(downloadId)

        // Cancel the ongoing progress notification
        notificationManager.cancel(notifId)

        val title = if (success) "Download Complete" else "Download Failed"
        val contentText = if (hideFilenames) "Transfer finished" else filename
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

        val builder = NotificationCompat.Builder(context, CHANNEL_COMPLETIONS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle(title)
            .setContentText(contentText)
            .setSubText(subText)
            .setContentIntent(pendingOpenIntent)
            .setAutoCancel(true)
            .setOngoing(false)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(if (success) NotificationCompat.CATEGORY_STATUS else NotificationCompat.CATEGORY_ERROR)
            .setVisibility(if (hideFilenames) NotificationCompat.VISIBILITY_PRIVATE else NotificationCompat.VISIBILITY_PUBLIC)

        notificationManager.notify(notifId, builder.build())
    }

    fun showStaleNotification(source: String = "Chrome", pcName: String = "Desktop-PC") {
        cancelActiveProgressNotifications()
        val notifId = STALE_NOTIFICATION_ID
        val subText = "${source.replaceFirstChar { it.uppercase() }} · $pcName"
        val builder = NotificationCompat.Builder(context, CHANNEL_COMPLETIONS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle("PC Offline")
            .setContentText("Transfer stalled — connection lost with $pcName")
            .setSubText(subText)
            .setAutoCancel(true)
            .setOngoing(false)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)

        notificationManager.notify(notifId, builder.build())
    }

    fun cancelActiveProgressNotifications() {
        for (id in activeProgressIds()) {
            notificationManager.cancel(id)
        }
        notificationManager.cancel(SUMMARY_ID)
    }

    /** True if any download progress bar is currently shown. */
    fun hasActiveProgress(): Boolean = activeProgressIds().isNotEmpty()

    fun cancelStaleNotification() {
        notificationManager.cancel(STALE_NOTIFICATION_ID)
    }

    fun cancelNotification(downloadId: String) {
        notificationManager.cancel(getNotificationId(downloadId))
    }

    fun cleanRemovedProgressNotifications(currentActiveIds: Set<String>) {
        val currentNotifIds = currentActiveIds.map { getNotificationId(it) }.toSet()
        for (id in activeProgressIds()) {
            if (id !in currentNotifIds) {
                notificationManager.cancel(id)
            }
        }
    }

    fun cancelAll() {
        notificationManager.cancelAll()
    }

    fun cancelGroupSummary() {
        notificationManager.cancel(SUMMARY_ID)
    }

    fun showGroupSummary(
        activeCount: Int,
        totalSpeedBytes: Long,
        totalRemainingBytes: Long? = null,
        activeItems: List<Pair<String, Float?>> = emptyList(),
        source: String = "Chrome",
        pcName: String = "Desktop-PC",
        hideFilenames: Boolean = false
    ) {
        if (activeCount < 3) {
            cancelGroupSummary()
            return
        }

        val parts = mutableListOf<String>()
        parts.add("$activeCount Downloads Active")
        if (totalRemainingBytes != null && totalRemainingBytes > 0) {
            parts.add("${formatBytes(totalRemainingBytes)} left")
        }
        parts.add("${formatSpeed(totalSpeedBytes)} total")
        val summaryTitle = parts.joinToString(" • ")
        val subText = "${source.replaceFirstChar { it.uppercase() }} · $pcName"

        val openIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingOpenIntent = PendingIntent.getActivity(
            context,
            SUMMARY_ID,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val inboxStyle = NotificationCompat.InboxStyle()
            .setBigContentTitle(summaryTitle)
            .setSummaryText(subText)

        for ((index, item) in activeItems.withIndex()) {
            val (name, pct) = item
            val displayName = if (hideFilenames) "Download #${index + 1}" else name
            val pctText = if (pct != null) "${String.format(Locale.US, "%.0f", pct)}%" else "LIVE"
            inboxStyle.addLine("$displayName - $pctText")
        }

        val summaryBuilder = NotificationCompat.Builder(context, CHANNEL_DOWNLOADS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setColor(BRAND_COLOR)
            .setContentTitle(summaryTitle)
            .setContentText(subText)
            .setSubText(subText)
            .setStyle(inboxStyle)
            .setContentIntent(pendingOpenIntent)
            .setTimeoutAfter(PROGRESS_TIMEOUT_MS)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setGroup(GROUP_DOWNLOADS)
            .setGroupSummary(true)
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_SUMMARY)
            .setVisibility(if (hideFilenames) NotificationCompat.VISIBILITY_PRIVATE else NotificationCompat.VISIBILITY_PUBLIC)

        notificationManager.notify(SUMMARY_ID, summaryBuilder.build())
    }

    private fun formatBytes(bytes: Long): String {
        if (bytes >= 1024L * 1024 * 1024) {
            return String.format(Locale.US, "%.1f GB", bytes / (1024.0 * 1024.0 * 1024.0))
        }
        if (bytes >= 1024L * 1024) {
            return String.format(Locale.US, "%.1f MB", bytes / (1024.0 * 1024.0))
        }
        if (bytes >= 1024L) {
            return String.format(Locale.US, "%.0f KB", bytes / 1024.0)
        }
        return "$bytes B"
    }

    private fun formatSpeed(bytesPerSec: Long): String {
        if (bytesPerSec >= 1024 * 1024) {
            return String.format(Locale.US, "%.1f MB/s", bytesPerSec / (1024.0 * 1024.0))
        }
        if (bytesPerSec >= 1024) {
            return String.format(Locale.US, "%.0f KB/s", bytesPerSec / 1024.0)
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
