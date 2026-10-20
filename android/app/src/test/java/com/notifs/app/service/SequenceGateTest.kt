package com.notifs.app.service

import com.notifs.app.service.SequenceGate.Decision
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SequenceGateTest {

    private val pairing = "11111111-1111-4111-8111-111111111111"

    private fun eval(last: StreamPosition?, incoming: StreamPosition, incomingPairing: String = pairing) =
        SequenceGate.evaluate(pairing, incomingPairing, last, incoming)

    @Test
    fun firstPushIsAccepted() {
        assertEquals(Decision.Accept, eval(null, StreamPosition(epoch = 1000, seq = 1)))
    }

    @Test
    fun increasingSeqWithinEpochIsAccepted() {
        assertEquals(Decision.Accept, eval(StreamPosition(1000, 5), StreamPosition(1000, 6)))
    }

    @Test
    fun duplicateAndReorderedPushesAreDropped() {
        assertTrue(eval(StreamPosition(1000, 5), StreamPosition(1000, 5)) is Decision.Drop)
        assertTrue(eval(StreamPosition(1000, 5), StreamPosition(1000, 3)) is Decision.Drop)
    }

    @Test
    fun serverRestartIsAcceptedEvenThoughSeqResets() {
        // Bug #3: the server restarted, its seq counter is back at 1. Previously dropped until
        // seq caught up with 500; now the new epoch starts a fresh stream.
        assertEquals(Decision.Accept, eval(StreamPosition(1000, 500), StreamPosition(2000, 1)))
    }

    @Test
    fun serverClockSteppingBackwardsDoesNotSilenceThePhone() {
        assertEquals(Decision.Accept, eval(StreamPosition(2000, 500), StreamPosition(1500, 1)))
    }

    @Test
    fun legacyServerWithoutEpochUsesPlainSeqOrdering() {
        assertEquals(Decision.Accept, eval(StreamPosition(0, 4), StreamPosition(0, 5)))
        assertTrue(eval(StreamPosition(0, 5), StreamPosition(0, 4)) is Decision.Drop)
    }

    @Test
    fun pushesForAnotherPairingAreDropped() {
        val other = "22222222-2222-4222-8222-222222222222"
        assertTrue(eval(null, StreamPosition(1000, 1), incomingPairing = other) is Decision.Drop)
    }

    @Test
    fun unsequencedDevPushesAreAccepted() {
        assertEquals(Decision.Accept, eval(StreamPosition(1000, 9), StreamPosition(0, 0), incomingPairing = ""))
    }
}
