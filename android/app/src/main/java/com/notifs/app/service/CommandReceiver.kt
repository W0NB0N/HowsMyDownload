package com.notifs.app.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** Handles the Pause / Resume / Restart buttons on download notifications. */
class CommandReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != NotificationHelper.ACTION_COMMAND) return
        val downloadId = intent.getStringExtra(NotificationHelper.EXTRA_DOWNLOAD_ID) ?: return
        val action = DownloadCommands.Action.fromWire(
            intent.getStringExtra(NotificationHelper.EXTRA_COMMAND)
        ) ?: return
        val state = intent.getStringExtra(NotificationHelper.EXTRA_STATE).orEmpty()

        // goAsync keeps the process alive for the network call (PairingApi caps it at 8s)
        val pendingResult = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                DownloadCommands.dispatch(context.applicationContext, downloadId, action, state)
            } finally {
                pendingResult.finish()
            }
        }
    }
}
