/**
 * Popup script for Download Notifs.
 * Manages configuration inputs, displays live download status, ping checks backend health,
 * generates pairing QR codes, and handles mobile device handshake.
 * Terminal Dark Theme Edition.
 */

// Hosted relay used unless the user enters another server. Classic script, so it can't import
// background/api.js; test_api.js checks the two values match.
const DEFAULT_SERVER_URL = "https://hmd-api.duckdns.org";

document.addEventListener("DOMContentLoaded", async () => {
  const serverUrlInput = document.getElementById("server-url");
  const pcNameInput = document.getElementById("pc-name");
  const enabledToggle = document.getElementById("enabled-toggle");
  const statusBadge = document.getElementById("status-badge");
  const serverStatusPill = document.getElementById("server-status-pill");
  const serverErrorText = document.getElementById("server-error-text");
  const downloadsContainer = document.getElementById("downloads-container");
  const downloadCount = document.getElementById("download-count");

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
  document.getElementById("version-tag").textContent = `v${chrome.runtime.getManifest().version}`;
  const headerSammy = document.getElementById("header-sammy");

  const PAIR_BTN_HTML = `<svg width="13" height="13" viewBox="0 0 12 12" fill="currentColor" shape-rendering="crispEdges" aria-hidden="true"><path fill-rule="evenodd" d="M0 0h5v5H0zM1 1v3h3V1zM7 0h5v5H7zM8 1v3h3V1zM0 7h5v5H0zM1 8v3h3V8zM2 2h1v1H2zM9 2h1v1H9zM2 9h1v1H2zM7 7h2v2H7zM10 7h2v1h-2zM9 9h1v3H9zM11 10h1v2h-1z"/></svg><span>pair device</span>`;
  const EMPTY_HTML = '<div class="empty-state"><span class="sammy s-chill" style="--k: 3" role="img" aria-label="Sammy sitting back on the grass"></span><span>// no transfers in progress</span></div>';
  const STATE_LABELS = {
    starting: "Starting",
    downloading: "Downloading",
    paused: "Paused",
    completed: "Complete",
    failed: "Failed"
  };
  const STATE_TONES = {
    starting: "var(--c-flag)",
    downloading: "var(--c-signal)",
    paused: "var(--c-warn)",
    completed: "var(--c-signal)",
    failed: "var(--c-fail)"
  };

  let pairingPollInterval = null;
  // Display only: the header Sammy pose, and download speed derived from consecutive samples
  let shownPaired = false;
  let shownActiveCount = 0;
  let shownEnabled = true;
  const speedById = new Map(); // download id -> { bytes, at, speed }

  // 1. Load initial settings
  const settings = await chrome.storage.local.get({
    serverUrl: DEFAULT_SERVER_URL,
    pcName: "Desktop-PC",
    enabled: true,
    lastSample: null,
    lastSampleTime: null,
    serverOnline: false,
    lastServerError: null,
    isPaired: false,
    pairingId: null,
    pairingSecret: null,
    pairingCode: null,
    encryptionKey: null
  });

  serverUrlInput.value = settings.serverUrl;
  pcNameInput.value = settings.pcName;
  enabledToggle.checked = settings.enabled;

  updateUI(settings.lastSample, settings.enabled, settings.lastSampleTime);
  checkBackendHealth(settings.serverUrl);
  updatePairingUI(settings.isPaired);
  // The background only hears about a phone-side unpair from a 401 on its next upload,
  // which never comes while nothing is downloading. Ask the server whenever the popup opens.
  if (settings.isPaired && settings.pairingId && settings.pairingSecret) {
    validatePairingSession(settings.serverUrl, settings.pairingId, settings.pairingSecret);
  }

  // 2. Setting change handlers
  serverUrlInput.addEventListener("change", () => {
    const newUrl = serverUrlInput.value.trim() || DEFAULT_SERVER_URL;
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
    const sUrl = (serverUrlInput.value.trim() || DEFAULT_SERVER_URL).replace(/\/+$/, "");
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
      
      // Generate client-side AES-256 encryption key for field-level filename encryption
      const encKeyBytes = new Uint8Array(32);
      crypto.getRandomValues(encKeyBytes);
      const encKeyHex = Array.from(encKeyBytes).map(b => b.toString(16).padStart(2, "0")).join("");

      await chrome.storage.local.set({
        pairingId: pairingData.pairing_id,
        pairingSecret: pairingData.secret,
        pairingCode: pairingData.code,
        encryptionKey: encKeyHex,
        isPaired: false
      });

      // Render QR code (encryption key is passed purely via optical scan to phone)
      const qrPayload = JSON.stringify({
        server_url: sUrl,
        code: pairingData.code,
        pc_name: hostname,
        enc_key: encKeyHex
      });

      if (typeof window.renderQRCode === "function") {
        window.renderQRCode(qrCanvas, qrPayload, 172);
      }

      qrCodeText.textContent = pairingData.code;
      qrExpiryText.textContent = "expires in 5m · scan with app";

      unpairedView.classList.add("hidden");
      qrContainer.classList.remove("hidden");
      updatePairingUI(false);

      // Start polling for pairing claim
      startPairingPoll(sUrl, pairingData.pairing_id, pairingData.secret);

    } catch (err) {
      alert(`Failed to create pairing: ${err.message}`);
    } finally {
      pairBtn.disabled = false;
      pairBtn.innerHTML = PAIR_BTN_HTML;
    }
  });

  qrCancelBtn.addEventListener("click", () => {
    stopPairingPoll();
    qrContainer.classList.add("hidden");
    unpairedView.classList.remove("hidden");
    updatePairingUI(false);
  });

  unpairBtn.addEventListener("click", async () => {
    const sUrl = (serverUrlInput.value.trim() || DEFAULT_SERVER_URL).replace(/\/+$/, "");
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
      encryptionKey: null,
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
    shownPaired = isPaired;
    updateHeaderSammy();
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
      // If currently displaying QR code modal waiting for phone to claim, keep QR visible
      if (qrContainer && !qrContainer.classList.contains("hidden")) {
        pairingBadge.textContent = "WAITING";
        pairingBadge.className = "pairing-status-badge status-waiting";
        return;
      }
      unpairedView.classList.remove("hidden");
      qrContainer.classList.add("hidden");
    }
  }

  async function validatePairingSession(serverUrl, pairingId, secret) {
    try {
      const cleanUrl = (serverUrl || DEFAULT_SERVER_URL).replace(/\/+$/, "");
      const res = await fetch(`${cleanUrl}/v1/pairings/${pairingId}`, {
        headers: { "Authorization": `Bearer ${secret}` },
        signal: AbortSignal.timeout(3000)
      });

      if (res.status === 401 || res.status === 403 || res.status === 404) {
        // Pairing was deleted on server (e.g. by phone)
        console.warn("[How's My Download] Server confirmed pairing was revoked. Resetting UI.");
        await chrome.storage.local.set({
          isPaired: false,
          pairingId: null,
          pairingSecret: null,
          pairingCode: null,
          encryptionKey: null
        });
        updatePairingUI(false);
      }
    } catch {
      // Ignore network errors on passive check
    }
  }

  // Clear the list like the app's "clear notifications": active downloads return with the
  // next sample (~2s), finished ones were already reported and stay gone.
  document.getElementById("clear-downloads-btn").addEventListener("click", async () => {
    const { lastSample } = await chrome.storage.local.get("lastSample");
    if (lastSample) await chrome.storage.local.set({ lastSample: { ...lastSample, downloads: [] } });
    updateUI({ downloads: [] }, enabledToggle.checked);
  });

  // 5. Live update listener
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "SAMPLE_DISPATCHED") {
      if (message.payload) {
        updateUI(message.payload, enabledToggle.checked, Date.now());
      }
      if (typeof message.serverOnline === "boolean" || message.connectionState) {
        updateServerStatus(message.serverOnline, message.error, message.connectionState);
      }
      if (typeof message.isPaired === "boolean") {
        updatePairingUI(message.isPaired);
      }
    }
  });

  // 6. Reactive storage changes listener (instantly reflects unpair from phone or background worker)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local") {
      if (changes.isPaired !== undefined) {
        updatePairingUI(changes.isPaired.newValue === true);
      }
      if (changes.serverOnline !== undefined || changes.lastServerError !== undefined || changes.connectionState !== undefined) {
        chrome.storage.local.get(["serverOnline", "lastServerError", "connectionState"]).then(({ serverOnline, lastServerError, connectionState }) => {
          updateServerStatus(serverOnline, lastServerError, connectionState);
        });
      }
      if (changes.lastSample !== undefined && changes.lastSample.newValue) {
        chrome.storage.local.get(["enabled", "lastSampleTime"]).then(({ enabled, lastSampleTime }) => {
          updateUI(changes.lastSample.newValue, enabled, lastSampleTime);
        });
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

      updateServerStatus(response.online, response.error, response.connectionState);
    } catch (err) {
      updateServerStatus(false, err.message, "unreachable");
    }
  }

  function setServerStatusChecking() {
    serverStatusPill.className = "server-pill pill-checking";
    serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">CHECKING</span>';
    serverErrorText.classList.add("hidden");
  }

  function updateServerStatus(isOnline, errorMsg, connectionState) {
    if (connectionState === "reconnecting" || (!isOnline && errorMsg && errorMsg.toLowerCase().includes("reconnecting"))) {
      serverStatusPill.className = "server-pill pill-reconnecting";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">RECONNECTING</span>';
      if (errorMsg) {
        serverErrorText.textContent = `// ${errorMsg}`;
        serverErrorText.classList.remove("hidden");
      } else {
        serverErrorText.textContent = "// in backoff retry loop";
        serverErrorText.classList.remove("hidden");
      }
    } else if (connectionState === "unreachable" || (!isOnline && connectionState !== "connected")) {
      serverStatusPill.className = "server-pill pill-offline";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">UNREACHABLE</span>';
      if (errorMsg) {
        serverErrorText.textContent = `// ${errorMsg}`;
      } else {
        serverErrorText.textContent = "// server unreachable";
      }
      serverErrorText.classList.remove("hidden");
    } else if (isOnline || connectionState === "connected") {
      serverStatusPill.className = "server-pill pill-online";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">CONNECTED</span>';
      serverErrorText.classList.add("hidden");
    } else {
      serverStatusPill.className = "server-pill pill-checking";
      serverStatusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">CHECKING</span>';
      serverErrorText.classList.add("hidden");
    }
  }

  /**
   * Updates all dynamic UI elements from a sample payload.
   */
  function updateUI(sample, isEnabled, timestamp) {
    const downloads = sample?.downloads || [];
    renderDownloads(downloads, Date.parse(sample?.timestamp));
    updateBadge(downloads.length, isEnabled);
  }

  // Header pose: waiting for a scan › unpaired › syncing › paired and idle
  function updateHeaderSammy() {
    let pose = "key";
    if (!shownPaired && !qrContainer.classList.contains("hidden")) {
      pose = "deliver";
    } else if (!shownPaired) {
      pose = "think";
    } else if (shownEnabled && shownActiveCount > 0) {
      pose = "downloading";
    }
    headerSammy.className = `sammy s-${pose}`;
  }

  function updateBadge(activeCount, isEnabled) {
    shownActiveCount = activeCount;
    shownEnabled = isEnabled;
    updateHeaderSammy();
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

  function formatSpeed(bytesPerSec) {
    if (bytesPerSec >= 1024 * 1024) return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`;
    if (bytesPerSec >= 1024) return `${Math.round(bytesPerSec / 1024)} KB/s`;
    return `${Math.round(bytesPerSec)} B/s`;
  }

  // Bytes per second since the previous sample of the same download. The same sample can
  // arrive twice (runtime message + storage change), which keeps the last speed.
  function speedFor(dl, sampledAt) {
    const prev = speedById.get(dl.id);
    if (prev && sampledAt <= prev.at) return prev.speed;
    const speed = prev
      ? Math.max(0, (dl.bytes_downloaded - prev.bytes) / ((sampledAt - prev.at) / 1000))
      : null;
    speedById.set(dl.id, { bytes: dl.bytes_downloaded, at: sampledAt, speed });
    return speed;
  }

  function renderDownloads(downloads, sampledAt) {
    if (!downloads || downloads.length === 0) {
      downloadsContainer.innerHTML = EMPTY_HTML;
      return;
    }

    downloadsContainer.innerHTML = "";
    downloads.forEach((dl) => {
      const itemEl = document.createElement("div");
      itemEl.className = "download-item";

      // Sammy's pose and the badge follow the download's state; anything else reads as offline
      const state = Object.hasOwn(STATE_LABELS, dl.state) ? dl.state : null;
      const pose = state || "offline";
      const label = state ? STATE_LABELS[state] : String(dl.state || "unknown");
      const tone = state ? STATE_TONES[state] : "var(--c-muted)";
      const fillClass = { paused: "fill-paused", failed: "fill-failed" }[state] || (state ? "" : "fill-muted");

      const totalKnown = dl.total_bytes && dl.total_bytes > 0;
      const pct = totalKnown ? Math.min(100, (dl.bytes_downloaded / dl.total_bytes) * 100) : null;
      const currentMB = (dl.bytes_downloaded / (1024 * 1024)).toFixed(1);
      const totalMB = totalKnown ? (dl.total_bytes / (1024 * 1024)).toFixed(1) : "?";
      const speed = Number.isFinite(sampledAt) ? speedFor(dl, sampledAt) : null;
      const speedText = state === "downloading" && speed !== null ? ` · ${formatSpeed(speed)}` : "";

      itemEl.innerHTML = `
        <div class="row">
          <h3 class="download-name" title="${escapeHtml(dl.filename)}">${escapeHtml(dl.filename)}</h3>
          <span class="badge b-${pose}">${escapeHtml(label)}</span>
        </div>
        <div class="track" style="--p: ${totalKnown ? pct.toFixed(2) : 0}">
          <span class="sammy s-${pose}" style="--k: 1.1" role="img" aria-label="Sammy: ${escapeHtml(label.toLowerCase())}"></span>
          <div class="bar"><i class="${fillClass}${totalKnown ? "" : " indeterminate"}" style="width: ${totalKnown ? pct.toFixed(2) : 30}%;"></i></div>
        </div>
        <div class="download-stats">
          <span>${currentMB} / ${totalMB} MB${speedText}</span>
          <span class="download-pct" style="color: ${tone}">${totalKnown ? `${pct.toFixed(1)}%` : "LIVE"}</span>
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
