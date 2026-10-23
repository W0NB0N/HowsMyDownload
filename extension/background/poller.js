/**
 * Poller module for the Chrome Extension.
 * Watches chrome.downloads API, computes state snapshots, and sends periodic samples.
 * Supports single-report pause status: when a download enters paused state, it is reported once,
 * and no further samples are sent for that download until its state changes.
 *
 * Phone commands (pause/resume/restart) ride back on sample responses while a transfer is
 * active. When nothing is transferring but a download could still be controlled (paused, or
 * failed in the last hour), a "command watch" polls the server instead: every 3s for 10
 * minutes after the last activity, then every 30s via chrome.alarms.
 */

import { fetchCommands, sendSample } from "./api.js";

const POLL_INTERVAL_MS = 2000;
const ALARM_NAME = "download_notifs_keepalive";
const IDLE_TIMEOUT_MS = 6000;

const WATCH_ALARM_NAME = "hmd_command_watch";
const COMMAND_POLL_INTERVAL_MS = 3000;
const FAST_WATCH_WINDOW_MS = 10 * 60 * 1000;
const FAILED_WATCH_WINDOW_MS = 60 * 60 * 1000;
const MAX_RESTARTED_IDS = 100;

let pollIntervalId = null;
let commandWatchId = null;
let lastActiveTimestamp = 0;
let forceSend = false;
let recentlyFinishedDownloads = new Map(); // downloadId -> { item, timestamp, reported }
let reportedDownloads = new Map(); // downloadId -> { state, bytesReceived }
// Downloads replaced by a phone "restart": never reported again except once as "erased"
const restartedIds = new Set();
const erasedToReport = new Map(); // downloadId -> protocol item

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
  const download = {
    id: String(item.id),
    filename: extractFilename(item),
    bytes_downloaded: Math.max(0, item.bytesReceived || 0),
    total_bytes: item.totalBytes > 0 ? item.totalBytes : null,
    state: state,
    mime_type: item.mime || undefined
  };
  // Lets the phone offer "resume" (keeps the bytes) rather than only "restart"
  if (item.state === "interrupted" && item.canResume) {
    download.can_resume = true;
  }
  return download;
}

/**
 * Stops reporting a download that a phone "restart" is replacing, and queues a one-time
 * "erased" report so the server and phone drop it.
 */
export function markRestarted(item) {
  const id = String(item.id);
  restartedIds.add(id);
  while (restartedIds.size > MAX_RESTARTED_IDS) {
    restartedIds.delete(restartedIds.values().next().value);
  }
  recentlyFinishedDownloads.delete(item.id);
  reportedDownloads.delete(id);
  const erased = { ...toProtocolDownload(item), state: "erased" };
  delete erased.can_resume;
  erasedToReport.set(id, erased);
}

/**
 * Undoes markRestarted when the restart could not be carried out.
 */
export function unmarkRestarted(downloadId) {
  restartedIds.delete(String(downloadId));
  erasedToReport.delete(String(downloadId));
}

/**
 * Sends the next sample even if nothing changed, so the phone's notification reflects the
 * outcome of a command (including one that changed nothing).
 */
export function requestImmediateSample() {
  forceSend = true;
  startPolling();
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
    stopCommandWatch();
    return;
  }

  // 1. Query in_progress downloads from Chrome
  const inProgressItems = (await chrome.downloads.search({ state: "in_progress" }))
    .filter(item => !restartedIds.has(String(item.id)));
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
    if (!currentIds.has(id) && !recentlyFinishedDownloads.has(Number(id))) {
      reportedDownloads.delete(id);
    }
  }

  // Include recently finished items that need reporting
  let hasUnsentFinished = false;
  for (const [id, record] of recentlyFinishedDownloads.entries()) {
    if (currentIds.has(String(id)) || restartedIds.has(String(id))) {
      // Resumed (in progress again) or being restarted: the stale terminal record must not
      // be reported alongside the live state of the same id.
      recentlyFinishedDownloads.delete(id);
      continue;
    }
    if (!record.reported || (now - record.timestamp < 4000)) {
      downloadItems.push(toProtocolDownload(record.item));
      if (!record.reported) {
        hasUnsentFinished = true;
        record.reported = true;
      }
    } else if (now - record.timestamp >= 10000) {
      recentlyFinishedDownloads.delete(id);
      reportedDownloads.delete(String(id));
    }
  }

  // Downloads replaced by a restart are reported once as erased
  for (const item of erasedToReport.values()) {
    downloadItems.push(item);
    hasStateOrProgressChange = true;
  }
  erasedToReport.clear();

  // Determine whether to dispatch sample:
  // Dispatch if there is active transferring, an unsent state transition (like newly paused),
  // an unsent terminal item, or a command outcome to reflect.
  const shouldSend = hasActiveTransfer || hasStateOrProgressChange || hasUnsentFinished || forceSend;
  forceSend = false;

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
    await updateCommandWatch();
  }
}

/**
 * Starts the polling loop and registers keep-alive alarm.
 */
export function startPolling() {
  lastActiveTimestamp = Date.now();
  // Samples carry commands while polling, so the separate watch is not needed
  stopCommandWatch();

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
 * True if some download could still be paused/resumed/restarted from the phone even though
 * nothing is transferring: a paused download, or one that failed within the last hour.
 */
async function hasControllableDownloads() {
  const live = id => !restartedIds.has(String(id));
  const paused = await chrome.downloads.search({ state: "in_progress", paused: true });
  if (paused.some(item => live(item.id))) return true;
  const failed = await chrome.downloads.search({
    state: "interrupted",
    endedAfter: new Date(Date.now() - FAILED_WATCH_WINDOW_MS).toISOString()
  });
  return failed.some(item => live(item.id));
}

/**
 * Starts, keeps or stops the command watch depending on what could be controlled right now.
 */
export async function updateCommandWatch() {
  const { enabled, isPaired } = await chrome.storage.local.get({ enabled: true, isPaired: false });
  if (!enabled || !isPaired || pollIntervalId || !(await hasControllableDownloads())) {
    stopCommandWatch();
    return;
  }

  // Re-creating an alarm resets its schedule, so only create it once
  if (!(await chrome.alarms.get(WATCH_ALARM_NAME))) {
    chrome.alarms.create(WATCH_ALARM_NAME, { periodInMinutes: 0.5 });
  }
  if (!commandWatchId && Date.now() - lastActiveTimestamp < FAST_WATCH_WINDOW_MS) {
    console.log("[How's My Download] Watching for phone commands (every 3s).");
    commandWatchId = setInterval(commandWatchTick, COMMAND_POLL_INTERVAL_MS);
  }
}

async function commandWatchTick() {
  if (pollIntervalId || Date.now() - lastActiveTimestamp >= FAST_WATCH_WINDOW_MS) {
    // Polling took over, or the fast window ended (the 30s alarm continues)
    clearInterval(commandWatchId);
    commandWatchId = null;
    return;
  }
  await fetchCommands();
  // Stops the watch once unpaired, disabled, or nothing is left to control
  await updateCommandWatch();
}

/**
 * Stops both the fast command watch and its alarm.
 */
export function stopCommandWatch() {
  if (commandWatchId) {
    clearInterval(commandWatchId);
    commandWatchId = null;
  }
  chrome.alarms.clear(WATCH_ALARM_NAME);
}

/**
 * Checks if there are active downloads in Chrome and starts polling if so.
 */
export async function checkActiveDownloads() {
  const active = await chrome.downloads.search({ state: "in_progress" });
  if (active.some(item => !item.paused)) {
    startPolling();
  } else {
    // Only paused (or nothing) in progress: no samples to send, but stay reachable for
    // commands. Also covers a browser restart with paused or recently failed downloads.
    await updateCommandWatch();
  }
}

/**
 * Remembers a download that just completed or failed so the next sample reports it.
 */
export async function rememberFinished(downloadId) {
  if (restartedIds.has(String(downloadId))) return;
  const items = await chrome.downloads.search({ id: downloadId });
  if (items.length > 0) {
    recentlyFinishedDownloads.set(downloadId, {
      item: items[0],
      timestamp: Date.now(),
      reported: false
    });
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
    await rememberFinished(delta.id);
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
export async function handleAlarm(alarm) {
  if (alarm.name === ALARM_NAME) {
    checkActiveDownloads();
  } else if (alarm.name === WATCH_ALARM_NAME) {
    await fetchCommands();
    await updateCommandWatch();
  }
}
