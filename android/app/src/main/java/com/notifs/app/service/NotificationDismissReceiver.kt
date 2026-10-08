package com.notifs.app.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.notifs.app.data.PairingDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class NotificationDismissReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "NotifDismissReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == NotificationHelper.ACTION_DISMISSED) {
            val downloadId = intent.getStringExtra(NotificationHelper.EXTRA_DOWNLOAD_ID)
            if (!downloadId.isNullOrBlank()) {
                Log.d(TAG, "Notification dismissed by user for download: $downloadId")
                val dataStore = PairingDataStore(context)
                CoroutineScope(Dispatchers.IO).launch {
                    dataStore.markDownloadDismissed(downloadId)
                }
            }
        }
    }
}
