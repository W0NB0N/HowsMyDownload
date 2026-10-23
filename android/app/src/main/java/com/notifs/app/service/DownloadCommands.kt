package com.notifs.app.service

import android.content.Context
import android.util.Log
import com.notifs.app.data.DownloadRepository
import com.notifs.app.data.PairingApi
import com.notifs.app.data.PairingDataStore
import java.io.IOException

/**
 * Pause / resume / restart a PC download from the phone.
 *
 * The phone posts the command to the server, which queues it until the extension collects it
 * (within ~3s while a download is active or paused). Success shows up as the next progress
 * push; a failure (including "PC never collected it") arrives as a `command_result` push.
 */
object DownloadCommands {
    private const val TAG = "DownloadCommands"

    enum class Action(
        val wire: String,
        val label: String,
        val pendingLabel: String,
        val verb: String,
        val icon: Int
    ) {
        PAUSE("pause", "Pause", "Pausing…", "pause", android.R.drawable.ic_media_pause),
        RESUME("resume", "Resume", "Resuming…", "resume", android.R.drawable.ic_media_play),
        RESTART("restart", "Restart", "Restarting…", "restart", android.R.drawable.ic_popup_sync);

        companion object {
            fun fromWire(wire: String?): Action? = values().firstOrNull { it.wire == wire }
        }
    }

    sealed interface SendResult {
        data object Queued : SendResult
        data class Failed(val message: String) : SendResult
    }

    /** Every action that makes sense for a download in [state] (protocol state name). */
    fun availableActions(state: String, canResume: Boolean): List<Action> =
        when (state.lowercase()) {
            "downloading", "starting" -> listOf(Action.PAUSE, Action.RESTART)
            "paused" -> listOf(Action.RESUME, Action.RESTART)
            "failed" -> if (canResume) listOf(Action.RESUME, Action.RESTART) else listOf(Action.RESTART)
            else -> emptyList()
        }

    /**
     * Notification buttons. Restart is left off a running download there because it can't
     * ask for confirmation and a stray tap would throw the progress away; the app offers it.
     */
    fun notificationActions(state: String, canResume: Boolean): List<Action> =
        availableActions(state, canResume).filterNot {
            it == Action.RESTART && state.lowercase() in setOf("downloading", "starting")
        }

    /** Restart discards everything downloaded so far, unless the download already failed. */
    fun needsConfirmation(action: Action, state: String): Boolean =
        action == Action.RESTART && state.lowercase() != "failed"

    /** Text for an error code from the extension or server (see docs/protocol.md). */
    fun errorMessage(errorCode: String?, action: Action): String = when (errorCode) {
        "expired" -> "PC didn't respond. Is it awake with Chrome open?"
        "not_found" -> "That download is no longer in Chrome"
        "invalid_state" -> "Can't ${action.verb} it right now"
        "not_resumable" -> "Chrome can't resume this one. Try restart"
        "unsupported_url" -> "This download can't be restarted from its link"
        else -> "Chrome couldn't ${action.verb} the download"
    }

    /**
     * Sends [action] for [downloadId] and updates the app list and notification: "Pausing…"
     * right away, or the error if the request fails. Blocking network: call from Dispatchers.IO.
     */
    suspend fun dispatch(
        context: Context,
        downloadId: String,
        action: Action,
        fromState: String
    ): SendResult {
        val helper = NotificationHelper(context)
        DownloadRepository.markPending(downloadId, action.wire, fromState)
        helper.markCommandPending(downloadId, action)

        val result = send(PairingDataStore(context), downloadId, action)
        if (result is SendResult.Failed) {
            DownloadRepository.commandFailed(downloadId, result.message)
            helper.markCommandFailed(downloadId, action, result.message)
        }
        return result
    }

    private suspend fun send(
        dataStore: PairingDataStore,
        downloadId: String,
        action: Action
    ): SendResult {
        val info = dataStore.getPairingInfo()
        val serverUrl = info.serverUrl
        val pairingId = info.pairingId
        if (!info.isPaired || serverUrl.isNullOrBlank() || pairingId.isNullOrBlank()) {
            return SendResult.Failed("Not paired with a PC")
        }
        return try {
            val deviceSecret = dataStore.getDeviceSecret()
                ?: return SendResult.Failed("Re-pair this phone to control downloads")
            val response = PairingApi.sendCommand(serverUrl, pairingId, deviceSecret, downloadId, action.wire)
            when (response.code) {
                200, 202 -> {
                    Log.i(TAG, "Queued ${action.wire} for download $downloadId (PC last seen ${response.pcLastSeenSec}s ago)")
                    SendResult.Queued
                }
                401 -> SendResult.Failed("Pairing is no longer valid. Re-pair this phone")
                403 -> SendResult.Failed("Re-pair this phone to control downloads")
                429 -> SendResult.Failed("Too many commands. Wait a moment")
                else -> SendResult.Failed("Server rejected the command (HTTP ${response.code})")
            }
        } catch (e: IOException) {
            Log.w(TAG, "Command ${action.wire} not sent: ${e.message}")
            SendResult.Failed("Couldn't reach the server")
        } catch (e: Exception) {
            Log.e(TAG, "Command ${action.wire} failed unexpectedly", e)
            SendResult.Failed("Couldn't send the command")
        }
    }
}
