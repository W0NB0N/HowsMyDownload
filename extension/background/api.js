/**
 * API client module for the Chrome Extension.
 * Handles dispatching download samples to the backend server and managing local sample history.
 */

const MAX_HISTORY = 100;
let pendingRetrySample = null;

/**
 * Checks the connectivity and health of the backend server.
 * 
 * @param {string} serverUrl - Base URL of the backend server
 * @returns {Promise<{online: boolean, data?: Object, error?: string}>}
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
      return { online: true, data };
    }
    return { online: false, error: `HTTP ${res.status}: ${res.statusText}` };
  } catch (err) {
    return { online: false, error: err.message || "Connection refused" };
  }
}

/**
 * Dispatches a formatted sample payload to the backend server via POST /v1/samples.
 * Gracefully handles offline states, includes Bearer authentication, and buffers the latest sample.
 * 
 * @param {Object} sample - The SamplePayload conforming to Schema v1
 */
export async function sendSample(sample) {
  const { enabled, serverUrl, pairingSecret, pairingId } = await chrome.storage.local.get({
    enabled: true,
    serverUrl: "http://localhost:8000",
    pairingSecret: null,
    pairingId: "dev-local-pairing"
  });

  if (!enabled) {
    return;
  }

  // Inject active pairing_id if available
  if (pairingId) {
    sample.pairing_id = pairingId;
  }

  const cleanServerUrl = (serverUrl || "http://localhost:8000").replace(/\/+$/, "");
  const targetEndpoint = `${cleanServerUrl}/v1/samples`;

  // Always buffer the latest sample in local storage for history/replay & popup
  try {
    const { sampleHistory = [] } = await chrome.storage.local.get("sampleHistory");
    const updatedHistory = [...sampleHistory, sample].slice(-MAX_HISTORY);

    await chrome.storage.local.set({
      lastSample: sample,
      sampleHistory: updatedHistory,
      lastSampleTime: Date.now()
    });
  } catch (storageErr) {
    console.warn("[Download Notifs] Error updating local sample history:", storageErr);
  }

  // Build headers
  const headers = {
    "Content-Type": "application/json",
    "Accept": "application/json"
  };

  if (pairingSecret) {
    headers["Authorization"] = `Bearer ${pairingSecret}`;
  }

  // Attempt dispatch to server
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
      pendingRetrySample = null;
      const resData = await res.json();

      const timestamp = new Date(sample.timestamp).toLocaleTimeString();
      console.log(`[Download Notifs] Sample @ ${timestamp} -> POST /v1/samples 200 OK (${resData.processed} processed)`);
    } else {
      dispatchError = `Server responded with HTTP ${res.status}`;
      console.warn(`[Download Notifs] Server error: ${res.status} ${res.statusText}`);
    }
  } catch (fetchErr) {
    dispatchError = fetchErr.message || "Failed to fetch";
    pendingRetrySample = sample;
    console.warn(`[Download Notifs] Backend unreachable at ${targetEndpoint} (${dispatchError})`);
  }

  // Update server connection status in storage
  try {
    await chrome.storage.local.set({
      serverOnline: serverOnline,
      lastServerError: dispatchError,
      lastServerCheckTime: Date.now()
    });
  } catch {
    // Ignore storage errors
  }

  // Notify any active popup UI
  try {
    chrome.runtime.sendMessage({
      type: "SAMPLE_DISPATCHED",
      payload: sample,
      serverOnline: serverOnline,
      error: dispatchError
    }).catch(() => {
      // Ignore when popup is closed
    });
  } catch {
    // Ignore message routing errors
  }
}
