/**
 * API client module for the Chrome Extension.
 * Handles dispatching download samples and managing local sample history.
 */

const MAX_HISTORY = 50;

/**
 * Dispatches a formatted sample payload.
 * In Phase 1 (Standalone), logs the sample to console and saves it to local storage.
 * In Phase 4+, will POST to the backend server.
 * 
 * @param {Object} sample - The SamplePayload conforming to Schema v1
 */
export async function sendSample(sample) {
  const { enabled, serverUrl } = await chrome.storage.local.get({
    enabled: true,
    serverUrl: "http://localhost:8000"
  });

  if (!enabled) {
    return;
  }

  // Phase 1: Output detailed log in Service Worker console
  const timestamp = new Date(sample.timestamp).toLocaleTimeString();
  console.group(`[Download Notifs] Sample @ ${timestamp} (${sample.downloads.length} active)`);
  console.log("Payload:", sample);
  
  sample.downloads.forEach(dl => {
    const totalStr = dl.total_bytes ? `${(dl.total_bytes / (1024 * 1024)).toFixed(1)} MB` : "Unknown";
    const currentStr = `${(dl.bytes_downloaded / (1024 * 1024)).toFixed(1)} MB`;
    console.log(` -> [${dl.state.toUpperCase()}] ${dl.filename} (${currentStr} / ${totalStr}) [id: ${dl.id}]`);
  });
  console.groupEnd();

  // Save latest sample and append to history for popup & export/replay
  try {
    const { sampleHistory = [] } = await chrome.storage.local.get("sampleHistory");
    const updatedHistory = [...sampleHistory, sample].slice(-MAX_HISTORY);
    
    await chrome.storage.local.set({
      lastSample: sample,
      sampleHistory: updatedHistory,
      lastSampleTime: Date.now()
    });

    // Notify any open popup UI
    chrome.runtime.sendMessage({
      type: "SAMPLE_DISPATCHED",
      payload: sample
    }).catch(() => {
      // Ignore error if popup is closed
    });
  } catch (err) {
    console.error("[Download Notifs] Error saving sample state:", err);
  }
}
