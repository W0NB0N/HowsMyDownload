package com.notifs.app.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class AppDownloadItem(
    val id: String,
    val filename: String,
    val state: String,
    val bytesDownloaded: Long = 0L,
    val totalBytes: Long? = null,
    val percentage: Float? = null,
    val speedBytesSec: Long = 0L,
    val etaSeconds: Long? = null,
    // Failed downloads only: the browser can resume without starting over
    val canResume: Boolean = false,
    val updatedAt: Long = System.currentTimeMillis()
)

/** A pause/resume/restart sent from this phone that the PC hasn't visibly acted on yet. */
data class PendingCommand(val action: String, val fromState: String, val sentAt: Long)

/** Why the last command for a download failed, shown until the download's state changes. */
data class CommandFailure(val message: String, val state: String?)

object DownloadRepository {
    /**
     * A pending command is assumed lost after this long. Longer than the server's command
     * expiry (75s), which normally reports an uncollected command first.
     */
    const val PENDING_TIMEOUT_MS = 90_000L

    /** Failed downloads stay listed (and restartable) this long after they were last reported. */
    const val FAILED_RETENTION_MS = 60 * 60 * 1000L

    private val _downloads = MutableStateFlow<List<AppDownloadItem>>(emptyList())
    val downloadsFlow: StateFlow<List<AppDownloadItem>> = _downloads.asStateFlow()

    private val _pending = MutableStateFlow<Map<String, PendingCommand>>(emptyMap())
    val pendingFlow: StateFlow<Map<String, PendingCommand>> = _pending.asStateFlow()

    private val _failures = MutableStateFlow<Map<String, CommandFailure>>(emptyMap())
    val failuresFlow: StateFlow<Map<String, CommandFailure>> = _failures.asStateFlow()

    private val lock = Any()

    /**
     * Applies one push. The extension reports a failure only briefly, so failed downloads
     * missing from later pushes are kept (for restart) unless the push says they were erased.
     */
    fun applyPush(
        items: List<AppDownloadItem>,
        erasedIds: Set<String> = emptySet(),
        now: Long = System.currentTimeMillis()
    ) = synchronized(lock) {
        val incomingIds = items.map { it.id }.toSet()
        val retainedFailures = _downloads.value.filter {
            it.state == "failed" &&
                it.id !in incomingIds &&
                it.id !in erasedIds &&
                now - it.updatedAt < FAILED_RETENTION_MS
        }
        val merged = items + retainedFailures
        _downloads.value = merged
        reconcile(merged, now)
    }

    fun markPending(
        downloadId: String,
        action: String,
        fromState: String,
        now: Long = System.currentTimeMillis()
    ) = synchronized(lock) {
        _pending.value = _pending.value + (downloadId to PendingCommand(action, fromState, now))
        _failures.value = _failures.value - downloadId
    }

    /** The pending action for [downloadId] if it is still in [state] and not timed out. */
    fun pendingFor(
        downloadId: String,
        state: String,
        now: Long = System.currentTimeMillis()
    ): PendingCommand? {
        val pending = _pending.value[downloadId] ?: return null
        return pending.takeIf { it.fromState == state && now - it.sentAt < PENDING_TIMEOUT_MS }
    }

    fun commandFailed(downloadId: String, message: String) = synchronized(lock) {
        _pending.value = _pending.value - downloadId
        val state = _downloads.value.firstOrNull { it.id == downloadId }?.state
        _failures.value = _failures.value + (downloadId to CommandFailure(message, state))
    }

    /** Drops pending commands that timed out without any answer. */
    fun expirePending(now: Long = System.currentTimeMillis()) = synchronized(lock) {
        _pending.value = _pending.value.filterValues { now - it.sentAt < PENDING_TIMEOUT_MS }
    }

    fun clear() = synchronized(lock) {
        _downloads.value = emptyList()
        _pending.value = emptyMap()
        _failures.value = emptyMap()
    }

    /**
     * A pending command is resolved once its download changes state or disappears (a restart
     * erases the old id). A failure message is dropped once the download changes state.
     */
    private fun reconcile(items: List<AppDownloadItem>, now: Long) {
        val stateById = items.associate { it.id to it.state }
        _pending.value = _pending.value.filter { (id, pending) ->
            stateById[id] == pending.fromState && now - pending.sentAt < PENDING_TIMEOUT_MS
        }
        _failures.value = _failures.value.filter { (id, failure) ->
            id in stateById && (failure.state == null || stateById[id] == failure.state)
        }
    }
}
