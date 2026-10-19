package com.notifs.app.service

/**
 * Position of a push in the server's stream. The server's seq counter lives in memory and
 * restarts at 1 whenever the server restarts, so every push also carries `epoch` (the server's
 * boot time in ms) identifying which counter it came from. Legacy servers send no epoch (0).
 */
data class StreamPosition(val epoch: Long, val seq: Int)

/**
 * Decides whether an incoming FCM progress push should be rendered.
 * Pure logic, kept separate from the service so it can be unit tested.
 */
object SequenceGate {

    sealed interface Decision {
        data object Accept : Decision
        data class Drop(val reason: String) : Decision
    }

    /**
     * Within one epoch, only strictly increasing seq is accepted (drops FCM duplicates and
     * reordering). A different epoch is a new server instance and starts a fresh stream. Any
     * change counts, not just an increase, so a server clock that stepped backwards cannot
     * silence the phone; at worst a push from the old instance (FCM TTL is 30s) renders once.
     *
     * @param pairedId the pairing this phone currently belongs to (null if unpaired)
     * @param incomingPairingId pairing_id carried by the push (blank for dev test pushes)
     * @param last last accepted position for the current pairing (null if none yet)
     * @param incoming position carried by the push
     */
    fun evaluate(
        pairedId: String?,
        incomingPairingId: String,
        last: StreamPosition?,
        incoming: StreamPosition,
    ): Decision {
        if (!pairedId.isNullOrBlank() && incomingPairingId.isNotBlank() && incomingPairingId != pairedId) {
            return Decision.Drop("push for another pairing ($incomingPairingId)")
        }
        if (incoming.seq <= 0 || last == null || incoming.epoch != last.epoch) {
            return Decision.Accept
        }
        return if (incoming.seq > last.seq) {
            Decision.Accept
        } else {
            Decision.Drop("stale or duplicate: seq ${incoming.seq} <= ${last.seq} (epoch ${incoming.epoch})")
        }
    }
}
