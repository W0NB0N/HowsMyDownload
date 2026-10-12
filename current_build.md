# How's My Download (HMD) — Build Status & Architecture Topology

*Last Updated: Phase 8 Complete (Reliability, Queue Coalescing, Strict Sequence Numbering, Backoff Engine & Lock Screen Privacy Guard)*

---

## 1. Abstracted Module Graph

```mermaid
graph TD
    subgraph ChromeExtension["Chrome Extension (Manifest V3) — 'How's My Download'"]
        SW["service-worker.js\n(Lifecycle, Event Multiplexer, Health Check)"]
        POL["poller.js\n(Downloads Observer, 2s Tick, Single-Report Pause Status)"]
        API["api.js\n(Authed POST /v1/samples, Exponential Backoff 2s-30s, Live Connection State)"]
        QR_GEN["popup/qrcode.js\n(Pure JS Offline Canvas QR Generator - Dynamic Version Scaling)"]
        POP["popup/ (HTML, CSS, JS)\n(Live Monitor, QR Pairing Modal Guard, Reconnecting Pill, 340px Width)"]
        
        SW --> POL
        POL --> API
        API -->|Broadcasts SAMPLE_DISPATCHED & Health & connectionState| POP
        POP --> QR_GEN
        POP -->|Triggers POLL_NOW / Settings / Pair / Unpair| SW
    end

    subgraph AndroidClient["Android Client (Kotlin / Compose) — 'How's My Download'"]
        ACT_MAIN["MainActivity.kt & HomeScreen.kt\n(Dark Terminal UI, Content-Level Privacy Toggle, Active Pairing Card, Token Display)"]
        QR_SCAN["ui/QrScannerScreen.kt\n(CameraX Preview + ML Kit Barcode Analyzer HUD)"]
        THEME["ui/theme/ (Color.kt, Theme.kt)\n(Render-inspired Dark Palette)"]
        FCM_SVC["service/NotifFcmService.kt\n(FCM Ingress, Sequence Drop, Token Rotation Call, 90s Local Safety Net)"]
        NOTIF_HLP["service/NotificationHelper.kt\n(downloads_v3 IMPORTANCE_LOW, Summary ID 990, InboxStyle 3+ Group Summary, Content-Level Filename Redaction)"]
        DISMISS_RCV["service/NotificationDismissReceiver.kt\n(Swipe-away Dismissal Tracking)"]
        DATA_STORE["data/PairingDataStore.kt\n(DataStore: lastSeq, hideFilenames, Pairing State)"]

        ACT_MAIN --> THEME
        ACT_MAIN --> NOTIF_HLP
        ACT_MAIN --> DATA_STORE
        ACT_MAIN --> QR_SCAN
        QR_SCAN --> DATA_STORE
        FCM_SVC --> NOTIF_HLP
        FCM_SVC --> DATA_STORE
        NOTIF_HLP --> DISMISS_RCV
    end

    subgraph ProductionDeployment["Oracle Cloud Infrastructure (Production VM: 80.225.228.101)"]
        IPT["iptables & netfilter-persistent\n(Netfilter TCP 80 & 443 Ingress)"]
        NGINX["nginx.conf\n(Rate Limit 30r/s, SSL Termination, HSTS, Gzip, WS)"]
        CERT["Certbot / Let's Encrypt\n(Auto-renewing TLS: hmd-api.duckdns.org)"]
        SYS_SVC["systemd (notifs-api.service)\n(Docker Compose Daemon Orchestration)"]
        DKR["Docker Container (Python 3.12-slim)\n(Non-root appuser, Layer-Cached Wheels, Multi-worker Uvicorn, 127.0.0.1:8000)"]

        IPT --> NGINX
        CERT -.->|Certificates| NGINX
        SYS_SVC --> DKR
        NGINX -->|Reverse Proxy / HTTP 1.1| DKR
    end

    subgraph BackendServer["Server (FastAPI Engine & Tracker inside Container)"]
        MAIN["main.py\n(FastAPI App Factory, Lifespan, CORS, Root & Health Endpoints)"]
        API_SAMPLES["api/samples.py\n(POST /v1/samples Endpoint with Bearer Auth)"]
        API_PAIRINGS["api/pairings.py\n(POST /v1/pairings, /claim, GET/DELETE /v1/pairings/{id}, POST /{id}/token)"]
        API_HEALTH["api/health.py\n(GET /health & GET / Root Probes)"]
        AUTH["auth.py\n(SHA-256 Secret Hash & Bearer Dependency)"]
        SCHEMAS["schemas.py\n(Schema v1 Pydantic Models, UpdateTokenRequest/Response)"]
        CONFIG["config.py\n(Settings & Env Config)"]
        
        STORE_BASE["store/base.py\n(BasePairingStore ABC: update_fcm_token)"]
        STORE_MEM["store/memory.py\n(InMemoryPairingStore with 5m TTL & Attempt Limit)"]
        STORE_FS["store/firestore.py\n(FirestorePairingStore)"]

        TRK_MGR["tracker/manager.py\n(TrackerManager, Multi-DL Orchestration)"]
        THROT["throttler/push_throttler.py\n(State-Change Bypass, Queue Coalescing, Strict Sequence Numbering)"]
        TRK_DL["tracker/download.py\n(TrackedDownload State Machine)"]
        TRK_CALC["tracker/calculator.py\n(SpeedSmoother EMA, ETA, Percentage)"]
        
        NOTIF_BASE["notifier/base.py\n(BaseNotifier ABC with target_token)"]
        NOTIF_CONSOLE["notifier/console.py\n(ANSI Developer Terminal Color Notifier)"]
        NOTIF_FCM["notifier/fcm.py\n(Firebase Admin High-Priority Data Notifier with Revocation Cleanup)"]
        NOTIF_COMPOSITE["notifier/composite.py\n(Dual Multiplexer: Console + FCM)"]

        DKR --> MAIN
        MAIN --> API_SAMPLES
        MAIN --> API_PAIRINGS
        MAIN --> API_HEALTH
        API_SAMPLES --> AUTH
        API_PAIRINGS --> AUTH
        AUTH --> STORE_BASE
        STORE_MEM -.->|Implements| STORE_BASE
        STORE_FS -.->|Implements| STORE_BASE
        API_SAMPLES --> TRK_MGR
        TRK_MGR --> THROT
        TRK_MGR --> TRK_DL
        TRK_DL --> TRK_CALC
        THROT --> NOTIF_COMPOSITE
        NOTIF_COMPOSITE --> NOTIF_CONSOLE
        NOTIF_COMPOSITE --> NOTIF_FCM
        NOTIF_FCM -.->|Revocation Cleanup| STORE_BASE
        NOTIF_CONSOLE -.->|Implements| NOTIF_BASE
        NOTIF_FCM -.->|Implements| NOTIF_BASE
    end

    subgraph FirebaseCloud["Google Firebase Cloud Services"]
        FCM_SRV["Firebase Cloud Messaging (FCM)"]
        FS_DB["Cloud Firestore (Client-locked Rules)"]
    end

    subgraph DevTools["Testing & Verification Tools"]
        TLS_REPLAY["tools/sample_replay.py\n(Sample Stream Replayer)"]
        TLS_FCM["tools/fcm_test_sender.py\n(FCM Test Stream Pusher)"]
        TLS_EXT["extension/test_poller.js\n(Extension Unit Suite - 100% Pass)"]
        TEST_SRV["server/tests/\n(29 Pytest Suites - 100% Pass)"]
    end

    POL -.->|Schema v1 Samples via HTTPS| NGINX
    POP -->|POST /v1/pairings via HTTPS| NGINX
    QR_SCAN -->|POST /v1/pairings/{code}/claim via HTTPS| NGINX
    FCM_SVC -.->|POST /v1/pairings/{id}/token via HTTPS| NGINX
    STORE_FS -->|Firebase Admin SDK| FS_DB
    NOTIF_FCM -->|Firebase Admin SDK| FCM_SRV
    FCM_SRV -->|High-Priority Data Message| FCM_SVC
```

---

## 2. Implemented Modules & Responsibilities

| Module / Component | Path | Responsibility & Implemented State | Inter-module Connection |
|---|---|---|---|
| **Push Throttler** | `server/throttler/push_throttler.py` | Enforces rate limit window (2.0s) per pairing. Detects state transitions (starting, downloading $\rightarrow$ paused, completed, failed, or download added/removed) and bypasses timer immediately. Coalesces interim progress updates into the single latest `PushPayload`. Maintains monotonic `_seq_map` incremented ONLY upon actual over-the-wire dispatch. | Consumed by `TrackerManager` and dispatches to active Notifier. |
| **FCM Revocation Cleanup** | `server/notifier/fcm.py` | Intercepts `messaging.UnregisteredError` and `exceptions.InvalidArgumentError`, instantly purging stale pairing sessions from `BasePairingStore` (in-memory or Firestore). | Linked to `BasePairingStore` via dependency injection in `lifespan`. |
| **Token Refresh API** | `server/api/pairings.py` | Exposes `POST /v1/pairings/{pairing_id}/token` accepting `UpdateTokenRequest`, updating device token in storage (`update_fcm_token`) without re-pairing. | Interacted with by Android on `onNewToken`. |
| **Optimized Dockerfile** | `deploy/Dockerfile` | Separates dependency wheel installation into a dedicated cached layer before copying application source code, achieving instant rebuilds. Pruning dangling images reclaims disk space. | Used by Docker Compose in production and staging. |
| **Extension Backoff Engine** | `extension/background/api.js` | Automatically engages exponential backoff (2s, 4s, 8s, 16s, max 30s) when `POST /v1/samples` fails. Buffers newest sample, broadcasts `connectionState` (`connected`, `reconnecting`, `unreachable`), and dispatches latest sample upon reconnection. | Dispatches samples from `poller.js` and updates `popup.js`. |
| **Single-Report Pause Poller** | `extension/background/poller.js` | Detects paused downloads and dispatches a sample once on entering paused state. Halts polling and notification spam for paused items until status changes (resumed to downloading, completed, failed). | Feeds into `api.js` and Chrome downloads API. |
| **Extension Popup Status UI** | `extension/popup/` | Renders connection state pills (green CONNECTED, amber RECONNECTING, red UNREACHABLE, gray CHECKING). Widened to 340px with ellipsis protection. | Receives runtime messages and storage events from `api.js`. |
| **Android Sequence Dropper & Token Refresh** | `android/.../service/NotifFcmService.kt` | Compares incoming `seq` against DataStore `lastSeq`, dropping duplicates and out-of-order pushes (`seq <= lastSeq`). On `onNewToken`, automatically queries pairing info and dispatches `POST /v1/pairings/{id}/token` via OkHttp. Maintains 90s local safety net (`safetyNetJob`) alerting "PC Offline" if FCM stops during active transfers. | Updates `PairingDataStore` and interacts with `NotificationHelper`. |
| **Android Unlimited Grouping & Summary Header** | `android/.../service/NotificationHelper.kt` | Uncapped active download progress notifications. Fixes missing summary header by assigning positive `SUMMARY_ID = 990`, creating `downloads_v3` channel with `IMPORTANCE_LOW` & `GROUP_ALERT_SUMMARY`. For 3+ active downloads, posts collapsed summary header formatted as `"$activeCount Downloads Active • $remaining left • $totalSpeed total"` with `NotificationCompat.InboxStyle` before children; automatically cancels summary header when active downloads drop below 3. | Triggered by `NotifFcmService.kt`. |
| **Hide Filenames in Notifications (Content-Level Privacy Guard)** | `MainActivity.kt` & `NotificationHelper.kt` | Added `--privacy [ hide_filenames ]` terminal card with Render dark switch. Immediately re-renders existing on-screen notifications without waiting for ticks. Always hides filenames at the content level in all notifications (titles show "Downloading…" / "Download Paused", body shows stats / "Transfer finished", summary shows "Download #1 - 64%"). Filenames appear strictly inside the app UI (`DownloadItemCard`) and never in notifications. | Controlled by Compose UI, persisted in DataStore (`hide_filenames_in_notifs`), rendered by NotificationHelper. |
| **Pairing Storage Backends** | `server/store/` | `InMemoryPairingStore` and `FirestorePairingStore` supporting CRUD plus `update_fcm_token`. | Consumed by `pairings.py`, `auth.py`, and `fcm.py`. |
| **Server Tests** | `server/tests/` | 29 Pytest suites covering throttler, queue coalescing, strict sequencing, state-change bypass, token cleanup, token refresh, and tracker state machine (100% pass). | Automated CI/test runner. |

---

## 3. Phase 8 Task Checklist & Status

| Task | Component | Description | Status |
|---|---|---|:---:|
| **8.1 State-Change Bypass** | `server/throttler/push_throttler.py` | Detects starting, downloading $\rightarrow$ paused, completed, failed, or download added/removed. Bypasses rate limit timer and dispatches immediately. | **COMPLETE** |
| **8.2 Queue Coalescing** | `server/throttler/push_throttler.py` | Within 2.0s throttle windows, buffers only the single latest `PushPayload`, discarding interim progress samples to eliminate lag. | **COMPLETE** |
| **8.3 Strict Sequence Numbering** | `server/throttler/push_throttler.py` | Maintains monotonic sequence counter (`_seq_map`) incremented only upon actual over-the-wire dispatch, guaranteeing zero sequence gaps. | **COMPLETE** |
| **8.4 FCM Revocation Invalidation** | `server/notifier/fcm.py` | Intercepts `messaging.UnregisteredError` and `exceptions.InvalidArgumentError`, instantly purging revoked pairings from active store. | **COMPLETE** |
| **8.5 FCM Token Refresh Endpoint** | `server/api/pairings.py` | Exposes `POST /v1/pairings/{pairing_id}/token` (`UpdateTokenRequest`), updating device token in memory & Firestore without re-pairing. | **COMPLETE** |
| **8.6 Instant Docker Compose Builds** | `deploy/Dockerfile` | Caches pip dependency installation in a dedicated Docker layer before copying `server/`, making rebuilds instant. | **COMPLETE** |
| **8.7 Dangling Image Space Reclaiming** | `commands.txt` & `oracle-deploy.md` | Reclaims dangling images via `docker image prune -f` during builds to preserve VM disk space. | **COMPLETE** |
| **8.8 Extension Exponential Backoff** | `extension/background/api.js` | Exponential backoff engine (2s, 4s, 8s, 16s, max 30s) on fetch errors, buffering newest sample and broadcasting connection state. | **COMPLETE** |
| **8.9 Single-Report Pause Status** | `extension/background/poller.js` | Reports paused download status once upon transition, then halts polling/dispatching for that download until status changes. | **COMPLETE** |
| **8.10 FCM Ingress & Sequence Drop** | `android/.../NotifFcmService.kt` | Drops pushes with `seq <= lastSeq`. Automatically pushes refreshed token to server on `onNewToken` via OkHttp. | **COMPLETE** |
| **8.11 90s Local Safety Net** | `android/.../NotifFcmService.kt` | Local coroutine safety net cancelling active progress notifications and alerting "PC Offline" if FCM messages cease for 90s during active downloads. | **COMPLETE** |
| **8.12 Unlimited Grouping & Summary Header** | `android/.../NotificationHelper.kt` | Uncapped download notifications; `SUMMARY_ID = 990` and `downloads_v3` channel (`IMPORTANCE_LOW`); for 3+ downloads displays collapsed summary header (`$activeCount Downloads Active • $remaining left • $totalSpeed total`) with `InboxStyle`, auto-cancelling when active count < 3. | **COMPLETE** |
| **8.13 Content-Level Privacy Guard** | `MainActivity.kt` & `NotificationHelper.kt` | `--privacy [ hide_filenames ]` toggle card with instant re-render. Redacts filenames at content level so filenames appear only in app, and notifications show sanitized status text. | **COMPLETE** |

---

## 4. Communication Contracts Active

- **Root Probe**: `GET /` returning `{"service": "hows-my-download", "status": "online", "version": "0.1.0"}`.
- **Health Check**: `GET /health` returning `{"status": "ok", "version": "0.1.0", "timestamp": "..."}`.
- **Sample Ingestion**: Defined in `docs/protocol.md#1` (`POST /v1/samples` with `Authorization: Bearer <secret>`).
- **Pairing Handshake**: Defined in `docs/protocol.md#4` (`POST /v1/pairings` $\rightarrow$ QR Code $\rightarrow$ `POST /v1/pairings/{code}/claim`).
- **Token Refresh**: `POST /v1/pairings/{pairing_id}/token` with `{"fcm_token": "<new_device_token>"}` returning `{"status": "ok", "pairing_id": "..."}`.
- **FCM Data Delivery**: High-priority FCM data message with `seq`, `pairing_id`, `source`, `pc_name`, and serialized `downloads`.

---

## 5. Design System & Theme Tokens (Render-inspired Dark Terminal)

| Token | Hex / Value | Usage |
|---|---|---|
| `--bg-canvas` | `#09090c` / `#000000` | Deep terminal black background |
| `--bg-card` | `#111116` / `#141419` | Surface containers & cards |
| `--border-subtle` | `#23232c` | Minimalist dark borders |
| `--purple-brand` | `#8a05ff` | Primary action accent, focus glow, badge outlines, sequence tags, active switches |
| `--purple-light` | `#c084fc` | Command flag prefixes, ETA text, completed download state |
| `--green-neon` | `#61cf92` | Active download state, pulsing status LED, speed highlights, online pills, QR viewfinder |
| `--amber-warning` | `#fbbf24` | Reconnecting status pill and backoff retry notification |
| `--text-white` | `#ffffff` | Primary titles, filenames, terminal commands |
| `--text-dim` | `#a1a1aa` | Secondary stats, labels, progress details |
| `--text-muted` | `#52525b` | Comments, inactive indicators, timestamps |
| **Typography** | `Monospace / Code` | `ui-monospace, "JetBrains Mono", Menlo, Consolas` |
| **Iconography** | `11x11 Pixel Grid` | Custom pixel-matrix block glyphs ([`icon.png`](file:///d:/1shav/1shav.code/projects/notifs/icon.png)) |
