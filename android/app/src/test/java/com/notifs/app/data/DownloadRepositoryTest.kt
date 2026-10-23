package com.notifs.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DownloadRepositoryTest {

    private val t0 = 1_000_000L

    private fun item(id: String, state: String, at: Long = t0) =
        AppDownloadItem(id = id, filename = "f$id", state = state, updatedAt = at)

    private fun ids() = DownloadRepository.downloadsFlow.value.map { it.id }

    @Before
    fun reset() = DownloadRepository.clear()

    @Test
    fun failedDownloadsStayListedAfterTheExtensionStopsReportingThem() {
        DownloadRepository.applyPush(listOf(item("1", "failed"), item("2", "downloading")), now = t0)
        DownloadRepository.applyPush(listOf(item("2", "downloading")), now = t0 + 1_000)
        assertEquals(listOf("2", "1"), ids())
    }

    @Test
    fun retainedFailuresExpireAndErasedOnesGoAway() {
        DownloadRepository.applyPush(listOf(item("1", "failed"), item("3", "failed")), now = t0)

        DownloadRepository.applyPush(emptyList(), erasedIds = setOf("3"), now = t0 + 1_000)
        assertEquals(listOf("1"), ids())

        DownloadRepository.applyPush(emptyList(), now = t0 + DownloadRepository.FAILED_RETENTION_MS)
        assertEquals(emptyList<String>(), ids())
    }

    @Test
    fun aDownloadThatIsRunningAgainIsNotListedTwice() {
        DownloadRepository.applyPush(listOf(item("1", "failed")), now = t0)
        DownloadRepository.applyPush(listOf(item("1", "downloading")), now = t0 + 1_000)
        assertEquals(listOf("1"), ids())
        assertEquals("downloading", DownloadRepository.downloadsFlow.value.single().state)
    }

    @Test
    fun pendingCommandSurvivesStalePushesAndClearsOnStateChange() {
        DownloadRepository.applyPush(listOf(item("1", "downloading")), now = t0)
        DownloadRepository.markPending("1", "pause", "downloading", now = t0)

        // A push sent before the PC acted still shows the old state
        DownloadRepository.applyPush(listOf(item("1", "downloading")), now = t0 + 500)
        assertNotNull(DownloadRepository.pendingFor("1", "downloading", now = t0 + 500))

        DownloadRepository.applyPush(listOf(item("1", "paused")), now = t0 + 2_000)
        assertNull(DownloadRepository.pendingFor("1", "paused", now = t0 + 2_000))
        assertTrue(DownloadRepository.pendingFlow.value.isEmpty())
    }

    @Test
    fun restartClearsPendingWhenTheOldIdIsErased() {
        DownloadRepository.applyPush(listOf(item("1", "failed")), now = t0)
        DownloadRepository.markPending("1", "restart", "failed", now = t0)
        DownloadRepository.applyPush(listOf(item("2", "starting")), erasedIds = setOf("1"), now = t0 + 1_000)
        assertTrue(DownloadRepository.pendingFlow.value.isEmpty())
        assertEquals(listOf("2"), ids())
    }

    @Test
    fun pendingTimesOut() {
        DownloadRepository.applyPush(listOf(item("1", "paused")), now = t0)
        DownloadRepository.markPending("1", "resume", "paused", now = t0)
        val later = t0 + DownloadRepository.PENDING_TIMEOUT_MS
        assertNull(DownloadRepository.pendingFor("1", "paused", now = later))

        DownloadRepository.expirePending(now = later)
        assertTrue(DownloadRepository.pendingFlow.value.isEmpty())
    }

    @Test
    fun failureReplacesPendingAndLastsUntilTheStateChanges() {
        DownloadRepository.applyPush(listOf(item("1", "paused")), now = t0)
        DownloadRepository.markPending("1", "resume", "paused", now = t0)
        DownloadRepository.commandFailed("1", "PC didn't respond")

        assertTrue(DownloadRepository.pendingFlow.value.isEmpty())
        assertEquals("PC didn't respond", DownloadRepository.failuresFlow.value["1"]?.message)

        DownloadRepository.applyPush(listOf(item("1", "paused")), now = t0 + 1_000)
        assertNotNull(DownloadRepository.failuresFlow.value["1"])

        DownloadRepository.applyPush(listOf(item("1", "downloading")), now = t0 + 2_000)
        assertNull(DownloadRepository.failuresFlow.value["1"])
    }

    @Test
    fun sendingAgainClearsThePreviousFailure() {
        DownloadRepository.applyPush(listOf(item("1", "failed")), now = t0)
        DownloadRepository.commandFailed("1", "nope")
        DownloadRepository.markPending("1", "restart", "failed", now = t0 + 10)
        assertNull(DownloadRepository.failuresFlow.value["1"])
    }
}
