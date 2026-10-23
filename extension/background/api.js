/**
 * API client module for the Chrome Extension.
 * Handles dispatching download samples to the backend server with exponential backoff retry
 * and managing local sample history.
 */

import { encryptField, isValidKeyHex, truncateFilename } from "./crypto.js";

const MAX_HISTORY = 100;
const BACKOFF_STEPS = [2000, 4000, 8000, 16000, 30000];
const MAX_RETRIES_BEFORE_UNREACHABLE = 5;

let currentRetryIndex = 0;
let nextRetryAllowedTime = 0;
let retryTimerId = null;
let pendingRetrySample = null;
let currentConnectionState = "connected"; // "connected" | "reconnecting" | "unreachable"
let commandHandler = null;

/**
 * Registers the function that executes phone commands (pause/resume/restart). Commands arrive
 * on sample responses and from fetchCommands(). Kept as a callback so this module does not
 * import the command executor (which itself depends on this module).
 */
export function setCommandHandler(handler) {
  commandHandler = handler;
}

function dispatchCommands(commands) {
  if (!commandHandler || !Array.isArray(commands) || commands.length === 0) return;
  // Run after the current request finishes: executing a command triggers a new sample
  Promise.resolve()
    .then(() => commandHandler(commands))
    .catch(err => console.warn("[How's My Download] Command handling failed:", err));
}

/**
 * Clears local pairing state after the server rejected the current secret (pairing revoked).
 */
async function clearRevokedPairing() {
  resetBackoff();
  currentConnectionState = "connected";
  await chrome.storage.local.set({
    isPaired: false,
    pairingId: null,
    pairingSecret: null,
    pairingCode: null,
    encryptionKey: null,
    serverOnline: true,
    connectionState: "connected",
    lastServerError: null
  });
}

/**
 * True when the stored secret differs from the one a request was sent with: the secret was
 * rotated while the request was in flight, so its 401 is not a revocation.
 */
async function secretRotatedSince(sentSecret) {
  const { pairingSecret: currentSecret } = await chrome.storage.local.get({ pairingSecret: null });
  return Boolean(currentSecret) && currentSecret !== sentSecret;
}

async function pairedContext() {
  const ctx = await chrome.storage.local.get({
    enabled: true,
    serverUrl: "http://localhost:8000",
    pairingSecret: null,
    pairingId: null,
    isPaired: false
  });
  if (!ctx.enabled || !ctx.isPaired || !ctx.pairingSecret || !ctx.pairingId) return null;
  return { ...ctx, baseUrl: (ctx.serverUrl || "http://localhost:8000").replace(/\/+$/, "") };
}

/**
 * Collects pending phone commands (used while no transfer is active, so no samples are being
 * sent to carry them). Skipped while backing off from an unreachable server.
 *
 * @returns {Promise<number>} number of commands received
 */
export async function fetchCommands() {
  const ctx = await pairedContext();
  if (!ctx || Date.now() < nextRetryAllowedTime) return 0;

  try {
    const res = await fetch(`${ctx.baseUrl}/v1/pairings/${ctx.pairingId}/commands`, {
      method: "GET",
      headers: { "Accept": "application/json", "Authorization": `Bearer ${ctx.pairingSecret}` },
      signal: AbortSignal.timeout(4000)
    });
    if (res.ok) {
      const { commands = [] } = await res.json();
      dispatchCommands(commands);
      return commands.length;
    }
    if (res.status === 401 && !(await secretRotatedSince(ctx.pairingSecret))) {
      console.warn("[How's My Download] Server returned 401 (Pairing revoked). Resetting pairing status.");
      await clearRevokedPairing();
    }
  } catch (err) {
    console.warn(`[How's My Download] Could not fetch commands (${err.message || err})`);
  }
  return 0;
}

/**
 * Tells the server how a command ended; failures are forwarded to the phone. Best effort.
 *
 * @param {{command_id: string, download_id: string, action: string}} command
 * @param {boolean} ok
 * @param {string|null} error - one of the protocol's command error codes
 */
export async function reportCommandResult(command, ok, error = null) {
  const ctx = await pairedContext();
  if (!ctx) return;
  try {
    await fetch(`${ctx.baseUrl}/v1/pairings/${ctx.pairingId}/commands/${command.command_id}/result`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": `Bearer ${ctx.pairingSecret}`
      },
      body: JSON.stringify({ download_id: command.download_id, action: command.action, ok, error }),
      signal: AbortSignal.timeout(4000)
    });
  } catch (err) {
    console.warn(`[How's My Download] Could not report command result (${err.message || err})`);
  }
}

/**
 * Resets backoff state (e.g. on manual trigger, configuration change, or successful ping).
 */
export function resetBackoff() {
  currentRetryIndex = 0;
  nextRetryAllowedTime = 0;
  if (retryTimerId) {
    clearTimeout(retryTimerId);
    retryTimerId = null;
  }
}

/**
 * Returns current connection state.
 */
export function getConnectionState() {
  return currentConnectionState;
}

/**
 * Checks the connectivity and health of the backend server.
 * 
 * @param {string} serverUrl - Base URL of the backend server
 * @returns {Promise<{online: boolean, data?: Object, error?: string, connectionState: string}>}
 */
export async function checkServerHealth(serverUrl) {
  const url = (serverUrl || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/health`, {
      method: "GET",
      headers: { "Accept": "application/json" },
      signal: AbortSignal.timeout(3000)
    });

    if (res.ok) {
      const data = await res.json();
      resetBackoff();
      currentConnectionState = "connected";
      await chrome.storage.local.set({
        serverOnline: true,
        connectionState: "connected",
        lastServerError: null
      });
      return { online: true, data, connectionState: "connected" };
    }

    const err = `HTTP ${res.status}: ${res.statusText}`;
    return { online: false, error: err, connectionState: currentConnectionState };
  } catch (err) {
    return { online: false, error: err.message || "Connection refused", connectionState: currentConnectionState };
  }
}

/**
 * Builds the body sent to the server: a deep copy of the sample with every user-content field
 * (filename, mime_type) encrypted. Throws rather than ever returning plaintext.
 *
 * @param {Object} sample - SamplePayload with plaintext filenames (kept locally for the popup)
 * @param {string} encryptionKey - 64-char hex AES-256 key shared with the phone via QR
 * @returns {Promise<Object>}
 */
export async function prepareWirePayload(sample, encryptionKey) {
  if (!isValidKeyHex(encryptionKey)) {
    throw new Error("Missing encryption key. Re-pair the phone to enable end-to-end encryption.");
  }
  const payload = JSON.parse(JSON.stringify(sample));
  for (const dl of payload.downloads || []) {
    dl.filename = await encryptField(truncateFilename(dl.filename || `download-${dl.id}`), encryptionKey);
    if (dl.mime_type) {
      dl.mime_type = await encryptField(dl.mime_type, encryptionKey);
    }
  }
  return payload;
}

/**
 * Executes a deferred retry of the buffered pending sample.
 */
async function executeRetryPendingSample() {
  retryTimerId = null;
  if (pendingRetrySample) {
    const sampleToRetry = pendingRetrySample;
    await sendSample(sampleToRetry);
  }
}

/**
 * Dispatches a formatted sample payload to the backend server via POST /v1/samples.
 * Gracefully handles offline states with exponential backoff (2s, 4s, 8s, 16s, 30s),
 * includes Bearer authentication, and buffers the latest sample continuously.
 * 
 * @param {Object} sample - The SamplePayload conforming to Schema v1
 */
export async function sendSample(sample) {
  const { enabled, serverUrl, pairingSecret, pairingId, isPaired, encryptionKey } = await chrome.storage.local.get({
    enabled: true,
    serverUrl: "http://localhost:8000",
    pairingSecret: null,
    pairingId: null,
    isPaired: false,
    encryptionKey: null
  });

  if (!enabled) {
    return;
  }

  // Inject active pairing_id if available
  if (pairingId) {
    sample.pairing_id = pairingId;
  }

  // Always buffer the latest sample in local storage for history/replay & popup UI
  try {
    const { sampleHistory = [] } = await chrome.storage.local.get("sampleHistory");
    const updatedHistory = [...sampleHistory, sample].slice(-MAX_HISTORY);

    await chrome.storage.local.set({
      lastSample: sample,
      sampleHistory: updatedHistory,
      lastSampleTime: Date.now()
    });
  } catch (storageErr) {
    console.warn("[How's My Download] Error updating local sample history:", storageErr);
  }

  // If unpaired, don't dispatch to backend (no mobile recipient)
  if (!isPaired || !pairingSecret) {
    try {
      chrome.runtime.sendMessage({
        type: "SAMPLE_DISPATCHED",
        payload: sample,
        isPaired: false,
        connectionState: currentConnectionState
      }).catch(() => {});
    } catch {}
    return;
  }

  const cleanServerUrl = (serverUrl || "http://localhost:8000").replace(/\/+$/, "");
  const targetEndpoint = `${cleanServerUrl}/v1/samples`;

  const now = Date.now();

  // If currently waiting inside an exponential backoff window, buffer sample and schedule retry
  if (now < nextRetryAllowedTime) {
    pendingRetrySample = sample;
    console.log(`[How's My Download] In backoff window. Buffering latest sample (next attempt in ${Math.round((nextRetryAllowedTime - now) / 1000)}s).`);

    if (!retryTimerId) {
      retryTimerId = setTimeout(executeRetryPendingSample, Math.max(50, nextRetryAllowedTime - now));
    }

    try {
      chrome.runtime.sendMessage({
        type: "SAMPLE_DISPATCHED",
        payload: sample,
        serverOnline: false,
        connectionState: currentConnectionState,
        error: `Reconnecting (retry in ${Math.round((nextRetryAllowedTime - now) / 1000)}s)`,
        isPaired: true
      }).catch(() => {});
    } catch {}
    return;
  }

  // Encrypt user-content fields with the client-side key. Fail closed: if encryption is not
  // possible the sample is dropped, never sent in plaintext.
  let payloadToSend;
  try {
    payloadToSend = await prepareWirePayload(sample, encryptionKey);
  } catch (cryptoErr) {
    console.error("[How's My Download] Sample not sent:", cryptoErr.message);
    try {
      await chrome.storage.local.set({ lastServerError: cryptoErr.message });
      chrome.runtime.sendMessage({
        type: "SAMPLE_DISPATCHED",
        payload: sample,
        connectionState: currentConnectionState,
        error: cryptoErr.message,
        isPaired: true
      }).catch(() => {});
    } catch {}
    return;
  }

  // Build headers
  const headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": `Bearer ${pairingSecret}`
  };

  let serverOnline = false;
  let dispatchError = null;

  try {
    const res = await fetch(targetEndpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payloadToSend),
      signal: AbortSignal.timeout(4000)
    });

    if (res.ok) {
      serverOnline = true;
      currentRetryIndex = 0;
      nextRetryAllowedTime = 0;
      currentConnectionState = "connected";
      pendingRetrySample = null;
      if (retryTimerId) {
        clearTimeout(retryTimerId);
        retryTimerId = null;
      }

      const resData = await res.json();
      const timestamp = new Date(sample.timestamp).toLocaleTimeString();
      console.log(`[How's My Download] Sample @ ${timestamp} -> POST /v1/samples 200 OK (${resData.processed} processed)`);
      dispatchCommands(resData.commands);
    } else {
      if (res.status === 401 && await secretRotatedSince(pairingSecret)) {
        // The secret was rotated while this request was in flight: not a revocation.
        console.log("[How's My Download] 401 with a superseded secret; retrying with the rotated one.");
        serverOnline = true;
        pendingRetrySample = sample;
        if (!retryTimerId) {
          retryTimerId = setTimeout(executeRetryPendingSample, 50);
        }
      } else if (res.status === 401) {
        console.warn("[How's My Download] Server returned 401 (Pairing revoked). Resetting pairing status.");
        serverOnline = true;
        dispatchError = null;
        await clearRevokedPairing();
      } else {
        dispatchError = `Server responded with HTTP ${res.status}`;
        console.warn(`[How's My Download] Server error: ${res.status} ${res.statusText}`);
      }
    }
  } catch (fetchErr) {
    dispatchError = fetchErr.message || "Failed to fetch";
    console.warn(`[How's My Download] Backend unreachable at ${targetEndpoint} (${dispatchError})`);
  }

  // If request failed and not 401 revoked pairing, apply exponential backoff
  if (!serverOnline && isPaired) {
    pendingRetrySample = sample;
    const backoffDelay = BACKOFF_STEPS[Math.min(currentRetryIndex, BACKOFF_STEPS.length - 1)];
    nextRetryAllowedTime = Date.now() + backoffDelay;
    currentRetryIndex++;

    if (currentRetryIndex >= MAX_RETRIES_BEFORE_UNREACHABLE) {
      currentConnectionState = "unreachable";
    } else {
      currentConnectionState = "reconnecting";
    }

    if (retryTimerId) {
      clearTimeout(retryTimerId);
    }
    retryTimerId = setTimeout(executeRetryPendingSample, backoffDelay);
    console.log(`[How's My Download] Backoff state: ${currentConnectionState} (attempt ${currentRetryIndex}, delay ${backoffDelay / 1000}s)`);
  }

  // Update server connection status in local storage
  try {
    await chrome.storage.local.set({
      serverOnline: serverOnline,
      connectionState: currentConnectionState,
      lastServerError: dispatchError,
      lastServerCheckTime: Date.now()
    });
  } catch (storageErr) {
    console.warn("[How's My Download] Storage update error:", storageErr);
  }

  // Broadcast dispatch result to popup UI
  try {
    chrome.runtime.sendMessage({
      type: "SAMPLE_DISPATCHED",
      payload: sample,
      serverOnline: serverOnline,
      connectionState: currentConnectionState,
      error: dispatchError,
      isPaired: isPaired && (dispatchError === null || !dispatchError.includes("401"))
    }).catch(() => {
      // Popup might be closed, ignore
    });
  } catch {
    // Context invalidated, ignore
  }
}
