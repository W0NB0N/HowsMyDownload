# Chrome Web Store Listing: How's My Download

Metadata, description and policy disclosures for publishing the extension to the Chrome Web Store. Keep the permission justifications in sync with [`extension/manifest.json`](../extension/manifest.json) and what the code does.

---

## 1. Store metadata

| Field | Value |
|---|---|
| **Name** | How's My Download |
| **Short name** | HMD |
| **Version** | `0.2.1` |
| **Category** | Productivity |
| **Summary (≤ 132 chars)** | Your browser's download progress, speed and ETA on your Android phone. Pause, resume or restart from there. E2E encrypted. |
| **Website** | `https://github.com/W0NB0N/HowsMyDownload` |
| **Support URL** | `https://github.com/W0NB0N/HowsMyDownload/issues` |

---

## 2. Detailed description

```text
Started a 6 GB ISO and walked away from your desk? How's My Download puts the download on your phone: a live progress bar with speed and time left, updated every 2 seconds, plus Pause, Resume and Restart buttons that act on your browser. Works in Chrome, Brave and other Chromium-based browsers.

FEATURES
• Live progress notifications on Android with speed, ETA and a progress bar, one per download.
• Remote control: pause, resume or restart a download from the notification or the app.
• Clear outcomes: "Download complete", "Download failed", and an alert if your PC goes offline mid-download.
• End-to-end encrypted filenames: names and file types are encrypted with AES-256-GCM on your PC. The key reaches your phone only inside the pairing QR code, so the relay server cannot read them.
• No account: pair by scanning a QR code.
• Light on battery: Android wakes the app briefly through Firebase Cloud Messaging; there is no always-on connection.

PRIVACY
• No accounts, no browsing history, no analytics.
• The server sees byte counts, download states, timing and your PC's name, never filenames.
• Open source, including a self-hosting guide if you prefer to run your own server.

Requires the companion Android app.
```

---

## 3. Permission justifications

### `downloads`
* **Reads** active and recent downloads (`state`, `paused`, `bytesReceived`, `totalBytes`, `filename`, `canResume`, and `url` for restarts) to report progress to the user's phone.
* **Acts only on the user's command from their paired phone**: `pause`, `resume`, and for *restart*, `cancel` plus `download` of the same URL plus `erase` of the old entry. The extension never starts, stops or removes a download on its own.

### `storage`
* Stores settings and pairing state locally: server URL, PC name, the pairing's bearer secret and the AES key shared with the phone.

### `alarms`
* A 1-minute keep-alive alarm while a download is in progress, so the Manifest V3 service worker isn't stopped mid-download.
* A 30-second alarm, only while a download is paused or recently failed, to check for commands from the phone.

### Host permissions (`https://*/*`, `http://localhost/*`, `http://127.0.0.1/*`)
* The relay server's URL is chosen by the user (self-hosting is supported), so it can't be fixed in the manifest. Plain HTTP is allowed only for `localhost` development.

---

## 4. Privacy disclosure

* **Personal information collected**: none.
* **Browsing history collected**: none. Only the downloads the user is running are read.
* **Authentication information**: a 256-bit bearer secret and an AES key, stored locally in extension storage.
* **Data transmitted** (over TLS, to the server the user configured):
  * byte counts, download states, timing and the PC name;
  * filenames and MIME types only as AES-GCM ciphertext.
