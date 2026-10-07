/**
 * Popup script for Download Notifs.
 * Manages configuration inputs, displays live download status, and allows exporting sample traces.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const serverUrlInput = document.getElementById("server-url");
  const pcNameInput = document.getElementById("pc-name");
  const enabledToggle = document.getElementById("enabled-toggle");
  const statusBadge = document.getElementById("status-badge");
  const downloadsContainer = document.getElementById("downloads-container");
  const downloadCount = document.getElementById("download-count");
  const exportTraceBtn = document.getElementById("export-trace-btn");
  const lastSampleTime = document.getElementById("last-sample-time");
  const pairBtn = document.getElementById("pair-btn");
  const qrContainer = document.getElementById("qr-container");

  // 1. Load initial settings
  const settings = await chrome.storage.local.get({
    serverUrl: "http://localhost:8000",
    pcName: "Desktop-PC",
    enabled: true,
    lastSample: null,
    lastSampleTime: null
  });

  serverUrlInput.value = settings.serverUrl;
  pcNameInput.value = settings.pcName;
  enabledToggle.checked = settings.enabled;

  updateUI(settings.lastSample, settings.enabled, settings.lastSampleTime);

  // 2. Setting change handlers
  serverUrlInput.addEventListener("change", () => {
    chrome.storage.local.set({ serverUrl: serverUrlInput.value.trim() });
  });

  pcNameInput.addEventListener("change", () => {
    chrome.storage.local.set({ pcName: pcNameInput.value.trim() || "Desktop-PC" });
  });

  enabledToggle.addEventListener("change", () => {
    const isEnabled = enabledToggle.checked;
    chrome.storage.local.set({ enabled: isEnabled });
    if (isEnabled) {
      chrome.runtime.sendMessage({ type: "CHECK_ACTIVE" });
    }
    updateBadge(downloadsContainer.querySelectorAll(".download-item").length, isEnabled);
  });

  // 3. Pairing toggle placeholder
  pairBtn.addEventListener("click", () => {
    qrContainer.classList.toggle("hidden");
  });

  // 4. Export sample trace handler (for dev/testing with tools/sample_replay.py)
  exportTraceBtn.addEventListener("click", async () => {
    const { sampleHistory = [] } = await chrome.storage.local.get("sampleHistory");
    if (sampleHistory.length === 0) {
      alert("No download sample trace recorded yet. Start a download first!");
      return;
    }

    const jsonStr = JSON.stringify(sampleHistory, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = `download-samples-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  // 5. Live update listener
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "SAMPLE_DISPATCHED" && message.payload) {
      updateUI(message.payload, enabledToggle.checked, Date.now());
    }
  });

  // Trigger poll on popup open
  chrome.runtime.sendMessage({ type: "POLL_NOW" });

  /**
   * Updates all dynamic UI elements from a sample payload.
   */
  function updateUI(sample, isEnabled, timestamp) {
    const downloads = sample?.downloads || [];
    renderDownloads(downloads);
    updateBadge(downloads.length, isEnabled);

    if (timestamp) {
      const timeStr = new Date(timestamp).toLocaleTimeString();
      lastSampleTime.textContent = `Last: ${timeStr}`;
    }
  }

  function updateBadge(activeCount, isEnabled) {
    if (!isEnabled) {
      statusBadge.textContent = "Disabled";
      statusBadge.className = "badge badge-disabled";
    } else if (activeCount > 0) {
      statusBadge.textContent = "Active";
      statusBadge.className = "badge badge-active";
    } else {
      statusBadge.textContent = "Idle";
      statusBadge.className = "badge badge-idle";
    }
    downloadCount.textContent = activeCount;
  }

  function renderDownloads(downloads) {
    if (!downloads || downloads.length === 0) {
      downloadsContainer.innerHTML = '<div class="empty-state">No downloads active in Chrome</div>';
      return;
    }

    downloadsContainer.innerHTML = "";
    downloads.forEach((dl) => {
      const itemEl = document.createElement("div");
      itemEl.className = "download-item";

      const totalKnown = dl.total_bytes && dl.total_bytes > 0;
      const pct = totalKnown ? Math.round((dl.bytes_downloaded / dl.total_bytes) * 100) : null;
      const currentMB = (dl.bytes_downloaded / (1024 * 1024)).toFixed(1);
      const totalMB = totalKnown ? (dl.total_bytes / (1024 * 1024)).toFixed(1) : "?";

      itemEl.innerHTML = `
        <div class="download-title-row">
          <span class="download-name" title="${escapeHtml(dl.filename)}">${escapeHtml(dl.filename)}</span>
          <span class="state-tag state-${dl.state}">${dl.state}</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill ${totalKnown ? "" : "progress-indeterminate"}" 
               style="width: ${totalKnown ? pct : 100}%;"></div>
        </div>
        <div class="download-stats">
          <span>${currentMB} MB / ${totalMB} MB</span>
          <span>${totalKnown ? `${pct}%` : "Indeterminate"}</span>
        </div>
      `;

      downloadsContainer.appendChild(itemEl);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }
});
