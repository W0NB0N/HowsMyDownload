/**
 * API client module for the Chrome Extension.
 * Handles dispatching download samples to the backend server with exponential backoff retry
 * and managing local sample history.
 */

const MAX_HISTORY = 100;
const BACKOFF_STEPS = [2000, 4000, 8000, 16000, 30000];
const MAX_RETRIES_BEFORE_UNREACHABLE = 5;

let currentRetryIndex = 0;
let nextRetryAllowedTime = 0;
let retryTimerId = null;
let pendingRetrySample = null;
let currentConnectionState = "connected"; // "connected" | "reconnecting" | "unreachable"

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
  const { enabled, serverUrl, pairingSecret, pairingId, isPaired } = await chrome.storage.local.get({
    enabled: true,
    serverUrl: "http://localhost:8000",
    pairingSecret: null,
    pairingId: null,
    isPaired: false
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
      body: JSON.stringify(sample),
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
    } else {
      if (res.status === 401) {
        console.warn("[How's My Download] Server returned 401 (Pairing revoked). Resetting pairing status.");
        serverOnline = true;
        currentConnectionState = "connected";
        resetBackoff();
        dispatchError = null;
        await chrome.storage.local.set({
          isPaired: false,
          pairingId: null,
          pairingSecret: null,
          pairingCode: null,
          serverOnline: true,
          connectionState: "connected",
          lastServerError: null
        });
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
