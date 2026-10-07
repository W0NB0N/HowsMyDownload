/**
 * Poller module for the Chrome Extension.
 * Watches chrome.downloads API, computes state snapshots, and sends periodic samples.
 */

import { sendSample } from "./api.js";

const POLL_INTERVAL_MS = 2000;
const ALARM_NAME = "download_notifs_keepalive";
const IDLE_TIMEOUT_MS = 6000;

let pollIntervalId = null;
let lastActiveTimestamp = 0;
let recentlyFinishedDownloads = new Map(); // downloadId -> { item, timestamp, reported }

/**
 * Extracts a clean basename from a file path or URL.
 */
function extractFilename(item) {
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
function mapDownloadState(item) {
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
function toProtocolDownload(item) {
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

  // 2. Filter active or recently completed/interrupted downloads
  const downloadItems = [];

  // Add all in-progress items
  for (const item of inProgressItems) {
    downloadItems.push(toProtocolDownload(item));
  }

  // Include recently finished items that need at least one report
  for (const [id, record] of recentlyFinishedDownloads.entries()) {
    if (!record.reported || (now - record.timestamp < 4000)) {
      downloadItems.push(toProtocolDownload(record.item));
      record.reported = true;
    } else if (now - record.timestamp >= 10000) {
      recentlyFinishedDownloads.delete(id);
    }
  }

  if (downloadItems.length > 0) {
    lastActiveTimestamp = now;

    const samplePayload = {
      pairing_id: pairingId,
      source: "chrome",
      pc_name: pcName,
      timestamp: new Date().toISOString(),
      downloads: downloadItems
    };

    await sendSample(samplePayload);
  } else {
    // Check if we should go idle
    if (now - lastActiveTimestamp > IDLE_TIMEOUT_MS) {
      stopPolling();
    }
  }
}

/**
 * Starts the polling loop and registers keep-alive alarm.
 */
export function startPolling() {
  lastActiveTimestamp = Date.now();

  if (!pollIntervalId) {
    console.log("[Download Notifs] Starting download poller (every 2s).");
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
    console.log("[Download Notifs] Poller entering idle state (no active downloads).");
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
  console.log(`[Download Notifs] Download created: ${downloadItem.id} (${downloadItem.filename || downloadItem.url})`);
  startPolling();
}

/**
 * Event handler for chrome.downloads.onChanged
 */
export async function handleDownloadChanged(delta) {
  console.log(`[Download Notifs] Download changed: ${delta.id}`, delta);

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
  console.log(`[Download Notifs] Download erased: ${downloadId}`);
  recentlyFinishedDownloads.delete(downloadId);
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
