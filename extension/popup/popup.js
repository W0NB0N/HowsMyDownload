document.addEventListener("DOMContentLoaded", async () => {
  const serverUrlInput = document.getElementById("server-url");
  const enabledToggle = document.getElementById("enabled-toggle");

  // Load saved preferences
  chrome.storage.local.get(["serverUrl", "enabled"], (res) => {
    if (res.serverUrl) serverUrlInput.value = res.serverUrl;
    if (res.enabled !== undefined) enabledToggle.checked = res.enabled;
  });

  serverUrlInput.addEventListener("change", () => {
    chrome.storage.local.set({ serverUrl: serverUrlInput.value });
  });

  enabledToggle.addEventListener("change", () => {
    chrome.storage.local.set({ enabled: enabledToggle.checked });
  });
});
