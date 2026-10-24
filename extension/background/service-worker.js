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
import { DEFAULT_SERVER_URL, checkServerHealth, setCommandHandler } from "./api.js";
import { handleCommands } from "./commands.js";

console.log("[How's My Download] Service worker starting up.");

// Phone commands (pause / resume / restart) delivered by the server
setCommandHandler(handleCommands);

// Initialize default storage on first install
chrome.runtime.onInstalled.addListener(async (details) => {
  console.log("[How's My Download] Extension installed / updated:", details.reason);
  const defaults = {
    serverUrl: DEFAULT_SERVER_URL,
    pcName: "Desktop-PC",
    enabled: true,
    isPaired: false,
    pairingId: null,
    pairingSecret: null
  };

  const current = await chrome.storage.local.get(Object.keys(defaults));
  const toSet = {};
  for (const [k, v] of Object.entries(defaults)) {
    if (current[k] === undefined) {
      toSet[k] = v;
    }
  }
  // Versions before 0.2.1 defaulted to a local dev server. Move unpaired installs still on
  // that old default to the hosted server; a paired install keeps whatever it pairs with.
  if (current.serverUrl === "http://localhost:8000" && !current.isPaired) {
    toSet.serverUrl = DEFAULT_SERVER_URL;
  }
  if (Object.keys(toSet).length > 0) {
    await chrome.storage.local.set(toSet);
  }

  // Check if any downloads are already running
  checkActiveDownloads();
});

// Resume on browser startup
chrome.runtime.onStartup.addListener(() => {
  console.log("[How's My Download] Browser startup detected.");
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
    chrome.storage.local.get({ serverUrl: DEFAULT_SERVER_URL }).then(({ serverUrl }) => {
      checkServerHealth(message.serverUrl || serverUrl).then(result => {
        sendResponse(result);
      });
    });
    return true;
  }
});

// Initial check when worker awakens
checkActiveDownloads();
