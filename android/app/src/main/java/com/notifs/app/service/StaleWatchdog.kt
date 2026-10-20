package com.notifs.app.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.notifs.app.data.DownloadRepository

/**
 * Local "PC offline" safety net. If no FCM update arrives for [TIMEOUT_MS] while a transfer
 * is active (laptop lid closed, Wi-Fi dropped), the phone says so instead of showing a frozen
 * progress bar.
 *
 * This used to be a coroutine in the FCM service's scope, which dies with the process. That's
 * exactly what Android does to an idle background app, so the alert often never fired. An
 * AlarmManager alarm survives process death.
 *
 * The alarm is exact where Android allows it (always below 12; with SCHEDULE_EXACT_ALARM,
 * pre-granted on 12-13, user-granted on 14+). Otherwise it is inexact and may fire minutes
 * late, after NotificationHelper.PROGRESS_TIMEOUT_MS has already removed the bars. So firing
 * must not depend on bars still being shown: being armed is the signal, because the alarm
 * is only armed while a transfer is active and disarmed on pause, finish or unpair.
 */
object StaleWatchdog {
    const val TIMEOUT_MS = 90_000L
    private const val TAG = "StaleWatchdog"
    private const val ACTION_STALE = "com.notifs.app.ACTION_STALE"
    private const val EXTRA_SOURCE = "source"
    private const val EXTRA_PC_NAME = "pc_name"

    private fun pendingIntent(context: Context, source: String, pcName: String, flags: Int): PendingIntent? {
        val intent = Intent(context, StaleWatchdogReceiver::class.java).apply {
            action = ACTION_STALE
            putExtra(EXTRA_SOURCE, source)
            putExtra(EXTRA_PC_NAME, pcName)
        }
        return PendingIntent.getBroadcast(context, 0, intent, flags or PendingIntent.FLAG_IMMUTABLE)
    }

    /** (Re)starts the countdown. Called on every push that has an actively transferring download. */
    fun arm(context: Context, source: String, pcName: String) {
        val alarmManager = context.getSystemService(AlarmManager::class.java) ?: return
        val pi = pendingIntent(context, source, pcName, PendingIntent.FLAG_UPDATE_CURRENT) ?: return
        val triggerAt = SystemClock.elapsedRealtime() + TIMEOUT_MS
        val canExact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarmManager.canScheduleExactAlarms()
        if (canExact) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
        } else {
            alarmManager.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
        }
    }

    /** Stops the countdown (nothing active, paused, finished, or unpaired). */
    fun disarm(context: Context) {
        val alarmManager = context.getSystemService(AlarmManager::class.java) ?: return
        val pi = pendingIntent(context, "", "", PendingIntent.FLAG_NO_CREATE) ?: return
        alarmManager.cancel(pi)
        pi.cancel()
    }

    internal fun onFired(context: Context, intent: Intent) {
        val helper = NotificationHelper(context)
        Log.w(TAG, "No FCM update for ${TIMEOUT_MS / 1000}s while transfers active: PC offline")
        helper.showStaleNotification(
            source = intent.getStringExtra(EXTRA_SOURCE) ?: "Chrome",
            pcName = intent.getStringExtra(EXTRA_PC_NAME) ?: "Desktop-PC",
        )
        DownloadRepository.clear()
    }
}

class StaleWatchdogReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        StaleWatchdog.onFired(context, intent)
    }
}
