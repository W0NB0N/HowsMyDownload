# Chrome Web Store Listing — How's My Download (HMD)

Metadata, descriptions, and policy disclosures for publishing **How's My Download** to the Chrome Web Store.

---

## 1. Store Metadata

| Field | Value |
|---|---|
| **Extension Name** | How's My Download |
| **Short Name** | HMD |
| **Version** | `0.1.0` |
| **Category** | Productivity / Developer Tools |
| **Summary (132 chars max)** | Mirror live PC download progress, ETA, and speeds to your phone in real time with zero-knowledge end-to-end encryption. |
| **Website** | `https://github.com/1shav/hows-my-download` |
| **Support URL** | `https://github.com/1shav/hows-my-download/issues` |

---

## 2. Detailed Description

```text
Ever started a 50GB game download, an ISO image, or large dataset, and walked away from your desk wondering when it will finish?

How's My Download (HMD) mirrors your PC's active browser download progress directly to your Android device in real time. Monitor transfer speeds, percentage, and accurate ETAs from your phone without returning to your PC.

⚡ KEY FEATURES:
• Real-time Notification Shades: View live progress bars, transfer speeds, and time remaining on your lock screen and ambient display.
• Zero-Knowledge Field-Level Encryption: File names are encrypted client-side using 256-bit AES-GCM before leaving your computer. The encryption key is shared exclusively with your phone via QR code — the server never sees your filenames.
• Multi-Download Aggregation: Cleanly monitors multiple concurrent downloads with adaptive progress bars.
• Minimalist Dark Terminal Aesthetic: High-contrast Render-inspired dark theme with responsive feedback.
• Instant QR Pairing: Pair your computer and mobile device in seconds with an offline optical handshake. No account registration or login required.
• Bandwidth & Battery Optimized: Intelligent queue coalescing, single-report pause detection, and adaptive backoff minimize battery drain and network usage.

🔒 PRIVACY & SECURITY FIRST:
• No Accounts Required: No email, passwords, or personal credentials stored.
• Field-Level Encryption: Your downloads remain strictly your business.
• Open Source: Fully auditable codebase across Chrome Extension, Python backend, and native Android app.
```

---

## 3. Chrome Web Store Permission Justifications

Chrome Web Store requires explicit single-purpose justifications for each requested permission:

### `downloads`
* **Purpose**: Used exclusively to read the progress of active downloads (`state`, `bytesReceived`, `totalBytes`, `filename`) to calculate remaining time and speeds.
* **Scope**: Read-only monitoring; never initiates or cancels downloads without user command.

### `storage`
* **Purpose**: Persists user configuration locally on the device (`serverUrl`, `pcName`, `pairingSecret`, and client-side `encryptionKey`).

### `alarms`
* **Purpose**: Schedules a 20-second keepalive alarm for the Manifest V3 background service worker to prevent Chrome from prematurely terminating the worker during in-progress downloads.

---

## 4. Privacy Disclosure

* **Personal Information Collected**: None.
* **Browsing History Collected**: None.
* **Authentication Information**: Ephemeral 256-bit Bearer secret and AES encryption key stored locally in extension storage.
* **Data Transmission**: Download metrics (percentage, speed, byte counts) and AES-GCM ciphertext filenames are transmitted exclusively over TLS to the user-configured backend endpoint.
