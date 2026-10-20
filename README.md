# How's My Download (HMD)

[![CI Pipeline](https://github.com/W0NB0N/How-sMyDownload/actions/workflows/ci.yml/badge.svg)](https://github.com/W0NB0N/How-sMyDownload/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![Android 14](https://img.shields.io/badge/Android-API%2026%E2%80%9335-3DDC84?logo=android&logoColor=white)
![Jetpack Compose](https://img.shields.io/badge/Jetpack%20Compose-2024.10-4285F4?logo=jetpackcompose&logoColor=white)
![Manifest V3](https://img.shields.io/badge/Chrome%20Extension-MV3-orange?logo=googlechrome&logoColor=white)
![Security](https://img.shields.io/badge/Security-AES--256--GCM-8a05ff)
![License](https://img.shields.io/badge/license-MIT-green)

> **Real-time browser download telemetry mirrored to your mobile notification shade with zero-knowledge field-level encryption, sub-second latency, and adaptive push coalescing.**

---

## ⚡ The Problem & The Solution

**The Problem**: You start downloading a 50GB game update, a Linux ISO, or a large dataset, and walk away from your desk. Checking download progress requires returning to your computer, remote desktop software, or maintaining battery-draining continuous screen-on sessions.

**The Solution**: **How's My Download** bridges Chrome's native download manager to Android's notification shade using Firebase Cloud Messaging (FCM). Live progress bars, transfer speeds, and ETAs appear on your lock screen and update every 2 seconds — while **end-to-end field-level AES-256-GCM encryption** ensures the server never sees your filenames.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph ClientPC["Desktop PC / Browser"]
        Chrome["Chrome Downloads API"] -->|Poll 2s| Poller["Extension Poller\n(Single-Report Pause Engine)"]
        Crypto["Web Crypto API\n(AES-256-GCM)"] -->|Encrypts Filenames| API["API Client\n(Exponential Backoff)"]
        Poller --> Crypto
        UI_Pop["Popup UI (Render Dark)\n(Live Monitor & QR Generator)"] -->|Displays QR with AES Key| Canvas["Offline Canvas QR"]
    end

    subgraph CloudInfra["Oracle Cloud Production VM (Ubuntu 24.04 LTS)"]
        Nginx["Nginx Reverse Proxy\n(Per-IP Rate Limit 5r/s + SSL)"] --> Uvicorn["Docker (Python 3.12)\nFastAPI Application"]
        Uvicorn -->|Auth & Validation| Router["Ingress Router\n(Max 50KB Payload Guard)"]
        Router --> RateLimit["Sliding Window Rate Limiter\n(10 samples / 10s per pairing)"]
        RateLimit --> Throttler["Push Throttler Engine\n(Queue Coalescing & State Bypass)"]
        Throttler --> Calc["Speed Smoother (EMA)\n& ETA Calculator"]
        Calc --> FcmNotifier["FCM Data Notifier\n(Auto-Purge Invalid Tokens)"]
    end

    subgraph MobileDevice["Android Mobile Device (API 26+)"]
        Camera["CameraX + ML Kit"] -->|Scans QR (Imports AES Key)| DataStore["App-private DataStore\n(Key + Device Secret, backup disabled)"]
        FCM_Service["NotifFcmService\n(FirebaseMessagingService)"] --> Dropper["Strict Sequence Dropper\n(seq <= lastSeq)"]
        Dropper --> LocalCrypto["CryptoUtils (AES-256-GCM)\n(Local Filename Decryptor)"]
        LocalCrypto --> NotifHelper["NotificationHelper\n(downloads_v3 IMPORTANCE_LOW)"]
        NotifHelper --> Shade["Android Notification Shade\n(Determinate Progress, Speed & ETA)"]
        Shade --> Watchdog["90s Local Safety Net\n(Alerts if PC goes offline)"]
    end

    API -->|POST /v1/samples (TLS + Bearer)| Nginx
    Canvas -.->|Optical Offline Link\n(AES Key never hits server)| Camera
    FcmNotifier -->|High-Priority Data Message| FCM_Service
```

---

## 🔒 Zero-Knowledge Security Model

Unlike traditional notification relays that transmit user download histories in plaintext to cloud servers, HMD implements a **Zero-Knowledge Field-Level Encryption** protocol:

1. **Optical Key Handshake**: When generating a pairing QR code, the Chrome extension generates a random 256-bit AES key using the Web Crypto API (`crypto.getRandomValues`). This key is embedded **exclusively** into the visual QR code payload.
2. **Server Zero-Knowledge**: The encryption key is **never transmitted** in the HTTP handshake to `/v1/pairings` or `/v1/pairings/{code}/claim`. The server has no mathematical capability to decrypt filenames.
3. **Field-Level AES-GCM**: Before dispatching download metrics to the server, the extension encrypts the filename into an authenticated ciphertext string (`enc:v1:<iv>:<ciphertext>`). The server only parses byte progress, speeds, and state transitions.
4. **Local Mobile Decryption**: Upon receiving the high-priority FCM data packet, the Android app extracts the AES key from its local secure DataStore and decrypts the filename on the device.
5. **Fail-Closed Encryption**: If the extension is paired but has no valid key, or encryption fails, the sample is dropped. A filename is never sent in plaintext. `mime_type` is encrypted too, and the phone shows "Encrypted file" for anything it cannot authenticate.
6. **Separate Credentials per Side**: The extension and the phone each hold their own 256-bit bearer secret, stored server-side only as a SHA-256 hash. Only the phone can change where its pushes go (FCM token refresh). Either side can unpair. Unknown pairings and wrong secrets both return `401`, so pairing IDs can't be probed.
7. **Instant Secret Rotation**: The extension's secret can be rotated with one click. The old secret is rejected immediately with `HTTP 401`, and the phone's pairing is unaffected.

**What the server still sees**: byte counts, download states, timing, and the PC name. Only user content (file names and types) is encrypted.

---

## 🚀 Key Engineering Highlights

### 1. Adaptive Push Coalescing & State Bypass
Every push wakes the phone, so the server caps progress pushes per pairing while keeping state changes instant. HMD's **Push Throttler** (`server/throttler/push_throttler.py`) applies:
- **Queue Coalescing**: Samples inside the 2.0-second throttle window replace earlier ones, so a burst (several downloads, reconnect retries) becomes at most one push per window.
- **State-Change Bypass**: Any state transition (`starting` $\rightarrow$ `downloading` $\rightarrow$ `paused` $\rightarrow$ `completed` $\rightarrow$ `failed`) or download addition/removal skips the throttle window.
- **Single-Report Pause Poller**: When a transfer pauses, the extension reports the status once and stops polling until the status changes.
- **No sends under locks**: State is updated under a lock, but FCM calls happen outside it, so one slow push never stalls other users.

### 2. Ordering, Restarts & the "PC Offline" Safety Net
- **Out-of-Order Rejection**: FCM can deliver out of order. Each push carries `(epoch, seq)`: a strictly increasing sequence number plus the server's boot time. The phone drops stale or duplicate pushes within one epoch and treats a new epoch (server restart) as a fresh stream (`SequenceGate.kt`).
- **4 KB budget**: FCM data messages are capped at 4 KB. The server packs downloads by priority into a 3.5 KB budget and reports anything it had to leave out.
- **Process-death-proof watchdog**: If a laptop lid closes or Wi-Fi drops mid-download, an `AlarmManager` alarm (re-armed by every update) alerts **"PC Offline — Transfer stalled"** after 90 s, even if Android has killed the app. `setTimeoutAfter` is a system-enforced backstop that removes orphaned progress bars.

### 3. Content-Level Privacy Guard
A native switch in the Android Compose UI (`--privacy [ hide_filenames ]`) redacts filenames at the content level across all notification channels. Filenames appear only inside the app, while shade notifications display sanitized status lines (`Downloading… • 45.2% • 8.4 MB/s`).

---

## 📊 Benchmarks

| Metric | Value | Source |
|---|---|---|
| **Server handling time per sample** | **1.5 ms p50 / 1.9 ms p95** | `tools/bench_server.py` (in-process, laptop) |
| **Single-worker throughput** | **~630 samples/s** | same |
| **FCM payload, one download** | **~360 B** of the 4 KB limit | same |
| **Progress pushes per pairing** | **≤ 1 per 2 s** (state changes immediate) | by design: `push_throttler.py` |
| **Server test coverage** | **82%** of server code (Firestore store covered by a separate emulator suite) | `pytest --cov` in CI |
| **Server → phone latency** | *measure on your device* | `adb logcat -s HMD_LATENCY` → `tools/latency_report.py` |

*Methods, environment details, and what hasn't been measured yet are in [`docs/metrics.md`](docs/metrics.md).*

---

## 🛠️ Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| **Extension** | JavaScript (ES Modules, Manifest V3) | Native Chrome Downloads API, Web Crypto AES-256-GCM, zero external dependencies |
| **Backend** | Python 3.12, FastAPI, Pydantic v2, Uvicorn | Async ASGI concurrency, strict schema validation, low memory overhead |
| **Mobile App** | Kotlin 2.0, Jetpack Compose, Material 3 | Declarative reactive UI, CameraX barcode scanning, Preferences DataStore |
| **Push Transport**| Firebase Cloud Messaging (FCM HTTP v1) | High-priority data delivery without persistent background battery drain |
| **Infrastructure**| Docker, Nginx, Let's Encrypt, Oracle Cloud | Production reverse proxy, TLS termination, sliding window rate limiting |
| **Testing & CI** | Pytest (+ Firestore emulator), Ruff, JUnit 4, Node:Test, GitHub Actions | All three clients tested in CI; extension tests run the real modules against a `chrome.*` fake; a cross-language test checks that Kotlin decrypts the extension's Web Crypto output |

---

## 💻 Quick Start & Development

### 1. Backend Server Setup

```bash
# Clone the repository
git clone https://github.com/W0NB0N/How-sMyDownload.git
cd How-sMyDownload

# Setup Python virtual environment
uv venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate

# Install with development dependencies
pip install -e "./server[dev]"

# Run test suite and linter
ruff check server
pytest server/tests

# Launch local development server
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Chrome Extension Sideloading

1. Open Google Chrome and navigate to `chrome://extensions`.
2. Toggle **Developer mode** in the top-right corner.
3. Click **Load unpacked** and select the [`extension/`](extension/) directory.
4. Click the HMD icon in the toolbar, enter your backend URL (e.g., `http://localhost:8000`), and click **Pair Device**.

### 3. Android Client Installation

1. Open [`android/`](android/) in **Android Studio Ladybug (2024.2+)** or later.
2. Add your Firebase `google-services.json` to [`android/app/`](android/app/).
3. Connect your Android device via USB / WiFi debugging.
4. Run `./gradlew assembleDebug` or install directly with `./gradlew installDebug`.
5. Open the app and tap **Scan QR Code** to pair with your browser.

---

## 📦 Production Deployment & Packaging

- **Oracle Cloud VM Setup**: Full automated provisioning script and deployment guide in [`deploy/docs/oracle-deploy.md`](deploy/docs/oracle-deploy.md).
- **Chrome Web Store Packaging**: Package a production-ready `.zip` archive via `python tools/package_extension.py` (Listing details in [`docs/store-listing.md`](docs/store-listing.md)).
- **Protocol Documentation**: Full Schema v1 specifications in [`docs/protocol.md`](docs/protocol.md).

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
