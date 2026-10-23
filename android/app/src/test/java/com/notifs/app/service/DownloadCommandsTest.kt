package com.notifs.app.service

import com.notifs.app.service.DownloadCommands.Action
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadCommandsTest {

    @Test
    fun actionsFollowTheDownloadState() {
        assertEquals(listOf(Action.PAUSE, Action.RESTART), DownloadCommands.availableActions("downloading", false))
        assertEquals(listOf(Action.PAUSE, Action.RESTART), DownloadCommands.availableActions("starting", false))
        assertEquals(listOf(Action.RESUME, Action.RESTART), DownloadCommands.availableActions("paused", false))
        assertEquals(listOf(Action.RESTART), DownloadCommands.availableActions("failed", false))
        assertEquals(listOf(Action.RESUME, Action.RESTART), DownloadCommands.availableActions("failed", true))
        assertEquals(emptyList<Action>(), DownloadCommands.availableActions("completed", false))
        assertEquals(emptyList<Action>(), DownloadCommands.availableActions("erased", false))
        assertEquals(listOf(Action.RESUME, Action.RESTART), DownloadCommands.availableActions("PAUSED", false))
    }

    @Test
    fun notificationsNeverOfferRestartOnARunningDownload() {
        assertEquals(listOf(Action.PAUSE), DownloadCommands.notificationActions("downloading", false))
        assertEquals(listOf(Action.PAUSE), DownloadCommands.notificationActions("starting", false))
        assertEquals(listOf(Action.RESUME, Action.RESTART), DownloadCommands.notificationActions("paused", false))
        assertEquals(listOf(Action.RESUME, Action.RESTART), DownloadCommands.notificationActions("failed", true))
    }

    @Test
    fun restartAsksForConfirmationUnlessTheDownloadAlreadyFailed() {
        assertTrue(DownloadCommands.needsConfirmation(Action.RESTART, "downloading"))
        assertTrue(DownloadCommands.needsConfirmation(Action.RESTART, "paused"))
        assertFalse(DownloadCommands.needsConfirmation(Action.RESTART, "failed"))
        assertFalse(DownloadCommands.needsConfirmation(Action.PAUSE, "downloading"))
    }

    @Test
    fun wireNamesRoundTrip() {
        for (action in Action.values()) {
            assertEquals(action, Action.fromWire(action.wire))
        }
        assertNull(Action.fromWire("erase"))
        assertNull(Action.fromWire(null))
    }

    @Test
    fun everyProtocolErrorCodeHasItsOwnMessage() {
        val codes = listOf("expired", "not_found", "invalid_state", "not_resumable", "unsupported_url", "browser_error")
        val messages = codes.map { DownloadCommands.errorMessage(it, Action.RESUME) }
        assertEquals(codes.size, messages.toSet().size)
        assertTrue(DownloadCommands.errorMessage("expired", Action.PAUSE).contains("PC"))
        // Unknown codes from a newer server still read sensibly
        assertEquals(
            DownloadCommands.errorMessage("browser_error", Action.PAUSE),
            DownloadCommands.errorMessage("something_new", Action.PAUSE)
        )
    }
}
