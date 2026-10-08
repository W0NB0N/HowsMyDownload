/**
 * Popup script for Download Notifs.
 * Manages configuration inputs, displays live download status, ping checks backend health,
 * generates pairing QR codes, and handles mobile device handshake.
 * Terminal Dark Theme Edition.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const serverUrlInput = document.getElementById("server-url");
  const pcNameInput = document.getElementById("pc-name");
  const enabledToggle = document.getElementById("enabled-toggle");
  const statusBadge = document.getElementById("status-badge");
  const serverStatusPill = document.getElementById("server-status-pill");
  const serverErrorText = document.getElementById("server-error-text");
  const downloadsContainer = document.getElementById("downloads-container");
  const downloadCount = document.getElementById("download-count");
  const exportTraceBtn = document.getElementById("export-trace-btn");
  const lastSampleTime = document.getElementById("last-sample-time");

  // Pairing elements
  const pairingBadge = document.getElementById("pairing-status-badge");
  const pairBtn = document.getElementById("pair-btn");
  const unpairedView = document.getElementById("pairing-unpaired-view");
  const qrContainer = document.getElementById("qr-container");
  const qrCanvas = document.getElementById("qr-canvas");
  const qrCodeText = document.getElementById("qr-code-text");
  const qrExpiryText = document.getElementById("qr-expiry-text");
  const qrCancelBtn = document.getElementById("qr-cancel-btn");
  const pairedView = document.getElementById("pairing-paired-view");
  const unpairBtn = document.getElementById("unpair-btn");

  let pairingPollInterval = null;

  // 1. Load initial settings
  const settings = await chrome.storage.local.get({
    serverUrl: "http://localhost:8000",
    pcName: "Desktop-PC",
    enabled: true,
    lastSample: null,
    lastSampleTime: null,
    serverOnline: false,
    lastServerError: null,
    isPaired: false,
    pairingId: null,
    pairingSecret: null,
    pairingCode: null
  });

  serverUrlInput.value = settings.serverUrl;
  pcNameInput.value = settings.pcName;
  enabledToggle.checked = settings.enabled;

  updateUI(settings.lastSample, settings.enabled, settings.lastSampleTime);
  checkBackendHealth(settings.serverUrl);
  updatePairingUI(settings.isPaired);

  // 2. Setting change handlers
  serverUrlInput.addEventListener("change", () => {
    const newUrl = serverUrlInput.value.trim() || "http://localhost:8000";
    serverUrlInput.value = newUrl;
    chrome.storage.local.set({ serverUrl: newUrl });
    checkBackendHealth(newUrl);
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

  // 3. Pairing handlers
  pairBtn.addEventListener("click", async () => {
    const sUrl = (serverUrlInput.value.trim() || "http://localhost:8000").replace(/\/+$/, "");
    const hostname = pcNameInput.value.trim() || "Desktop-PC";

    pairBtn.disabled = true;
    pairBtn.textContent = "generating qr...";

    try {
      const res = await fetch(`${sUrl}/v1/pairings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pc_name: hostname }),
        signal: AbortSignal.timeout(4000)
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const pairingData = await res.json();
      await chrome.storage.local.set({
        pairingId: pairingData.pairing_id,
        pairingSecret: pairingData.secret,
        pairingCode: pairingData.code,
        isPaired: false
      });

      // Render QR code
      const qrPayload = JSON.stringify({
        server_url: sUrl,
        code: pairingData.code,
        pc_name: hostname
      });

      if (typeof window.renderQRCode === "function") {
        window.renderQRCode(qrCanvas, qrPayload, 160);
      }

      qrCodeText.textContent = pairingData.code;
      qrExpiryText.textContent = "expires in 5m · scan with app";

      unpairedView.classList.add("hidden");
      qrContainer.classList.remove("hidden");

      // Start polling for pairing claim
      startPairingPoll(sUrl, pairingData.pairing_id, pairingData.secret);

    } catch (err) {
      alert(`Failed to create pairing: ${err.message}`);
    } finally {
      pairBtn.disabled = false;
      pairBtn.innerHTML = `
        <svg viewBox="0 0 11 11" width="11" height="11" class="btn-pixel-icon" shape-rendering="crispEdges">
          <rect x="3" y="1" width="5" height="4" fill="#61cf92" />
          <rect x="4" y="2" width="3" height="3" fill="#141419" />
          <rect x="2" y="5" width="7" height="5" fill="#8a05ff" />
          <rect x="5" y="7" width="1" height="2" fill="#61cf92" />
        </svg>
        <span>pair device (qr)</span>
      `;
    }
  });

  qrCancelBtn.addEventListener("click", () => {
    stopPairingPoll();
    qrContainer.classList.add("hidden");
    unpairedView.classList.remove("hidden");
  });

  unpairBtn.addEventListener("click", async () => {
    const sUrl = (serverUrlInput.value.trim() || "http://localhost:8000").replace(/\/+$/, "");
    const { pairingId, pairingSecret } = await chrome.storage.local.get(["pairingId", "pairingSecret"]);

    if (pairingId && pairingSecret) {
      try {
        await fetch(`${sUrl}/v1/pairings/${pairingId}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${pairingSecret}` }
        });
      } catch {
        // Ignore network errors on unpair
      }
    }

    await chrome.storage.local.set({
      pairingId: null,
      pairingSecret: null,
      pairingCode: null,
      isPaired: false
    });

    updatePairingUI(false);
  });

  function startPairingPoll(serverUrl, pairingId, secret) {
    stopPairingPoll();
    pairingPollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${serverUrl}/v1/pairings/${pairingId}`, {
          headers: { "Authorization": `Bearer ${secret}` }
        });

        if (res.ok) {
          const data = await res.json();
          if (data.is_claimed) {
            stopPairingPoll();
            await chrome.storage.local.set({ isPaired: true });
            updatePairingUI(true);
          }
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);
  }

  function stopPairingPoll() {
    if (pairingPollInterval) {
      clearInterval(pairingPollInterval);
      pairingPollInterval = null;
    }
  }

  function updatePairingUI(isPaired) {
    if (isPaired) {
      pairingBadge.textContent = "PAIRED";
      pairingBadge.className = "pairing-status-badge status-paired";
      unpairedView.classList.add("hidden");
      qrContainer.classList.add("hidden");
      pairedView.classList.remove("hidden");
    } else {
      pairingBadge.textContent = "UNPAIRED";
      pairingBadge.className = "pairing-status-badge status-unpaired";
      pairedView.classList.add("hidden");
      unpairedView.classList.remove("hidden");
      qrContainer.classList.add("hidden");
    }
  }

  // 4. Export sample trace handler (for dev/testing with tools/sample_replay.py)
  exportTraceBtn.addEventListener("click", async () => {
    const { sampleHistory = [] } = await chrome.storage.local.get("sampleHistory");
    if (sampleHistory.length === 0) {
      alert("No sample trace recorded yet. Start a download first.");
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
      if (typeof message.serverOnline === "boolean") {
        updateServerStatus(message.serverOnline, message.error);
      }
    }
  });

  // Trigger poll on popup open
  chrome.runtime.sendMessage({ type: "POLL_NOW" });

  /**
   * Pings the server /health endpoint to verify connectivity.
   */
  async function checkBackendHealth(targetUrl) {
    setServerStatusChecking();
    try {
      const response = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ type: "CHECK_HEALTH", serverUrl: targetUrl }, (res) => {
          if (chrome.runtime.lastError) {
            resolve({ online: false, error: chrome.runtime.lastError.message });
          } else {
            resolve(res || { online: false, error: "No response" });
          }
        });
      });

      updateServerStatus(response.online, response.error);
    } catch (err) {
      updateServerStatus(false, err.message);
    }
  }

  function setServerStatusChecking() {
    serverStatusPill.className = "server-pill pill-checking";
    serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">CHECKING</span>';
    serverErrorText.classList.add("hidden");
  }

  function updateServerStatus(isOnline, errorMsg) {
    if (isOnline) {
      serverStatusPill.className = "server-pill pill-online";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">ONLINE</span>';
      serverErrorText.classList.add("hidden");
    } else {
      serverStatusPill.className = "server-pill pill-offline";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">OFFLINE</span>';
      if (errorMsg) {
        serverErrorText.textContent = `// ${errorMsg}`;
        serverErrorText.classList.remove("hidden");
      } else {
        serverErrorText.classList.add("hidden");
      }
    }
  }

  /**
   * Updates all dynamic UI elements from a sample payload.
   */
  function updateUI(sample, isEnabled, timestamp) {
    const downloads = sample?.downloads || [];
    renderDownloads(downloads);
    updateBadge(downloads.length, isEnabled);

    if (timestamp) {
      const d = new Date(timestamp);
      const timeStr = d.toTimeString().split(" ")[0]; // HH:MM:SS
      lastSampleTime.textContent = timeStr;
    }
  }

  function updateBadge(activeCount, isEnabled) {
    statusBadge.innerHTML = '<span class="status-dot"></span><span class="status-label"></span>';
    const label = statusBadge.querySelector(".status-label");
    
    if (!isEnabled) {
      label.textContent = "DISABLED";
      statusBadge.className = "badge badge-disabled";
    } else if (activeCount > 0) {
      label.textContent = "ACTIVE";
      statusBadge.className = "badge badge-active";
    } else {
      label.textContent = "IDLE";
      statusBadge.className = "badge badge-idle";
    }
    downloadCount.textContent = activeCount;
  }

  function renderDownloads(downloads) {
    if (!downloads || downloads.length === 0) {
      downloadsContainer.innerHTML = '<div class="empty-state"><span class="cli-dim">// no transfers in progress</span></div>';
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
          <span>${currentMB}MB / ${totalMB}MB</span>
          <span class="download-stats-highlight">${totalKnown ? `${pct}%` : "LIVE"}</span>
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
