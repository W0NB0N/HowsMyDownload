/**
 * Main background Service Worker for Download Notifs.
 * Wires together the poller, event listeners, and lifecycle hooks.
 */

import {
  handleDownloadCreated,
  handleDownloadChanged,
  handleDownloadErased,
  handleAlarm,
  checkActiveDownloads,
  pollAndSample
} from "./poller.js";
import { checkServerHealth } from "./api.js";

console.log("[Download Notifs] Service worker starting up.");

// Initialize default storage on first install
chrome.runtime.onInstalled.addListener(async (details) => {
  console.log("[Download Notifs] Extension installed / updated:", details.reason);
  const defaults = {
    serverUrl: "http://localhost:8000",
    pcName: "Desktop-PC",
    enabled: true,
    pairingId: "dev-local-pairing"
  };

  const current = await chrome.storage.local.get(Object.keys(defaults));
  const toSet = {};
  for (const [k, v] of Object.entries(defaults)) {
    if (current[k] === undefined) {
      toSet[k] = v;
    }
  }
  if (Object.keys(toSet).length > 0) {
    await chrome.storage.local.set(toSet);
  }

  // Check if any downloads are already running
  checkActiveDownloads();
});

// Resume on browser startup
chrome.runtime.onStartup.addListener(() => {
  console.log("[Download Notifs] Browser startup detected.");
  checkActiveDownloads();
});

// Download lifecycle listeners
chrome.downloads.onCreated.addListener(handleDownloadCreated);
chrome.downloads.onChanged.addListener(handleDownloadChanged);
chrome.downloads.onErased.addListener(handleDownloadErased);

// Keep-alive alarm listener
chrome.alarms.onAlarm.addListener(handleAlarm);

// Message listener from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "POLL_NOW") {
    pollAndSample().then(() => sendResponse({ status: "ok" }));
    return true; // Keep channel open for async response
  }
  if (message.type === "CHECK_ACTIVE") {
    checkActiveDownloads().then(() => sendResponse({ status: "ok" }));
    return true;
  }
  if (message.type === "CHECK_HEALTH") {
    chrome.storage.local.get({ serverUrl: "http://localhost:8000" }).then(({ serverUrl }) => {
      checkServerHealth(message.serverUrl || serverUrl).then(result => {
        sendResponse(result);
      });
    });
    return true;
  }
});

// Initial check when worker awakens
checkActiveDownloads();
