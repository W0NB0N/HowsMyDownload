/**
 * Poller module for the Chrome Extension.
 * Watches chrome.downloads API, computes state snapshots, and sends periodic samples.
 * Supports single-report pause status: when a download enters paused state, it is reported once,
 * and no further samples are sent for that download until its state changes.
 */

import { sendSample } from "./api.js";

const POLL_INTERVAL_MS = 2000;
const ALARM_NAME = "download_notifs_keepalive";
const IDLE_TIMEOUT_MS = 6000;

let pollIntervalId = null;
let lastActiveTimestamp = 0;
let recentlyFinishedDownloads = new Map(); // downloadId -> { item, timestamp, reported }
let reportedDownloads = new Map(); // downloadId -> { state, bytesReceived }

/**
 * Extracts a clean basename from a file path or URL.
 */
export function extractFilename(item) {
  if (item.filename) {
    const normalized = item.filename.replace(/\\/g, "/");
    const parts = normalized.split("/");
    const name = parts[parts.length - 1];
    if (name) return name;
  }
  if (item.url) {
    try {
      const urlObj = new URL(item.url);
      const parts = urlObj.pathname.split("/").filter(Boolean);
      if (parts.length > 0) {
        return decodeURIComponent(parts[parts.length - 1]);
      }
    } catch {
      // Ignore URL parse error
    }
  }
  return `download-${item.id}`;
}

/**
 * Maps a Chrome DownloadItem to our protocol state.
 */
export function mapDownloadState(item) {
  if (item.state === "complete") {
    return "completed";
  }
  if (item.state === "interrupted") {
    return "failed";
  }
  if (item.paused) {
    return "paused";
  }
  if (item.bytesReceived === 0 && item.totalBytes <= 0) {
    return "starting";
  }
  return "downloading";
}

/**
 * Converts a Chrome DownloadItem to our protocol Schema v1 DownloadItem.
 */
export function toProtocolDownload(item) {
  const state = mapDownloadState(item);
  return {
    id: String(item.id),
    filename: extractFilename(item),
    bytes_downloaded: Math.max(0, item.bytesReceived || 0),
    total_bytes: item.totalBytes > 0 ? item.totalBytes : null,
    state: state,
    mime_type: item.mime || undefined
  };
}

/**
 * Gathers all currently active and recently terminal downloads and sends a sample.
 */
export async function pollAndSample() {
  const { enabled, pcName, pairingId } = await chrome.storage.local.get({
    enabled: true,
    pcName: "Desktop-PC",
    pairingId: "dev-local-pairing"
  });

  if (!enabled) {
    stopPolling();
    return;
  }

  // 1. Query in_progress downloads from Chrome
  const inProgressItems = await chrome.downloads.search({ state: "in_progress" });
  const now = Date.now();

  // 2. Track downloads and state transitions
  const downloadItems = [];
  let hasActiveTransfer = false;
  let hasStateOrProgressChange = false;
  const currentIds = new Set();

  for (const item of inProgressItems) {
    const strId = String(item.id);
    currentIds.add(strId);
    const protoItem = toProtocolDownload(item);
    const last = reportedDownloads.get(strId);

    if (protoItem.state === "downloading" || protoItem.state === "starting") {
      hasActiveTransfer = true;
      if (!last || last.state !== protoItem.state || last.bytesReceived !== protoItem.bytes_downloaded) {
        hasStateOrProgressChange = true;
      }
    } else if (protoItem.state === "paused") {
      // Send paused state once when transitioning into paused
      if (!last || last.state !== "paused") {
        hasStateOrProgressChange = true;
      }
    } else {
      if (!last || last.state !== protoItem.state) {
        hasStateOrProgressChange = true;
      }
    }

    downloadItems.push(protoItem);
  }

  // Clean up reportedDownloads for items no longer in progress
  for (const id of reportedDownloads.keys()) {
    if (!currentIds.has(id) && !recentlyFinishedDownloads.has(id)) {
      reportedDownloads.delete(id);
    }
  }

  // Include recently finished items that need reporting
  let hasUnsentFinished = false;
  for (const [id, record] of recentlyFinishedDownloads.entries()) {
    if (!record.reported || (now - record.timestamp < 4000)) {
      downloadItems.push(toProtocolDownload(record.item));
      if (!record.reported) {
        hasUnsentFinished = true;
        record.reported = true;
      }
    } else if (now - record.timestamp >= 10000) {
      recentlyFinishedDownloads.delete(id);
      reportedDownloads.delete(id);
    }
  }

  // Determine whether to dispatch sample:
  // Dispatch if there is active transferring, an unsent state transition (like newly paused),
  // or an unsent terminal item.
  const shouldSend = hasActiveTransfer || hasStateOrProgressChange || hasUnsentFinished;

  if (downloadItems.length > 0 && shouldSend) {
    lastActiveTimestamp = now;

    // Record reported states
    for (const item of downloadItems) {
      reportedDownloads.set(item.id, {
        state: item.state,
        bytesReceived: item.bytes_downloaded
      });
    }

    const samplePayload = {
      pairing_id: pairingId,
      source: "chrome",
      pc_name: pcName,
      timestamp: new Date().toISOString(),
      downloads: downloadItems
    };

    await sendSample(samplePayload);
  }

  // If no downloads are actively transferring and no unsent items remain (e.g. all paused or finished),
  // stop the polling interval immediately to prevent continuous network ticks.
  if (!hasActiveTransfer && !hasUnsentFinished) {
    stopPolling();
  }
}

/**
 * Starts the polling loop and registers keep-alive alarm.
 */
export function startPolling() {
  lastActiveTimestamp = Date.now();

  if (!pollIntervalId) {
    console.log("[How's My Download] Starting download poller (every 2s).");
    pollAndSample(); // immediate sample
    pollIntervalId = setInterval(pollAndSample, POLL_INTERVAL_MS);
  }

  // Ensure keep-alive alarm is registered (every 1 minute)
  chrome.alarms.create(ALARM_NAME, {
    periodInMinutes: 1
  });
}

/**
 * Stops the active polling loop and clears keep-alive alarm if idle.
 */
export function stopPolling() {
  if (pollIntervalId) {
    console.log("[How's My Download] Poller entering idle state (no active downloads).");
    clearInterval(pollIntervalId);
    pollIntervalId = null;
  }
  chrome.alarms.clear(ALARM_NAME);
}

/**
 * Checks if there are active downloads in Chrome and starts polling if so.
 */
export async function checkActiveDownloads() {
  const active = await chrome.downloads.search({ state: "in_progress" });
  if (active.length > 0) {
    startPolling();
  }
}

/**
 * Event handler for chrome.downloads.onCreated
 */
export function handleDownloadCreated(downloadItem) {
  console.log(`[How's My Download] Download created: ${downloadItem.id} (${downloadItem.filename || downloadItem.url})`);
  startPolling();
}

/**
 * Event handler for chrome.downloads.onChanged
 */
export async function handleDownloadChanged(delta) {
  console.log(`[How's My Download] Download changed: ${delta.id}`, delta);

  if (delta.state && (delta.state.current === "complete" || delta.state.current === "interrupted")) {
    const items = await chrome.downloads.search({ id: delta.id });
    if (items.length > 0) {
      recentlyFinishedDownloads.set(delta.id, {
        item: items[0],
        timestamp: Date.now(),
        reported: false
      });
    }
  }

  // Trigger an immediate sample so state changes are instant
  startPolling();
}

/**
 * Event handler for chrome.downloads.onErased
 */
export function handleDownloadErased(downloadId) {
  console.log(`[How's My Download] Download erased: ${downloadId}`);
  recentlyFinishedDownloads.delete(downloadId);
  reportedDownloads.delete(String(downloadId));
  pollAndSample();
}

/**
 * Event handler for chrome.alarms.onAlarm
 */
export function handleAlarm(alarm) {
  if (alarm.name === ALARM_NAME) {
    checkActiveDownloads();
  }
}
