# Current Build Status & Architecture Topology

*Last Updated: Phase 7 Completion (Oracle Cloud VM Production Deployment Suite & Docs)*

---

## 1. Abstracted Module Graph

```mermaid
graph TD
    subgraph ChromeExtension["Chrome Extension (Manifest V3)"]
        SW["service-worker.js\n(Lifecycle, Event Multiplexer, Health Check)"]
        POL["poller.js\n(Downloads Observer, 2s Tick, Keepalive Alarm)"]
        API["api.js\n(Authed POST /v1/samples with Bearer Secret)"]
        QR_GEN["popup/qrcode.js\n(Pure JS Offline Canvas QR Generator)"]
        POP["popup/ (HTML, CSS, JS)\n(Live Monitor, QR Pairing Modal, Unpair Flow)"]
        
        SW --> POL
        POL --> API
        API -->|Broadcasts SAMPLE_DISPATCHED & Health| POP
        POP --> QR_GEN
        POP -->|Triggers POLL_NOW / Settings / Pair / Unpair| SW
    end

    subgraph AndroidClient["Android Client (Kotlin / Compose)"]
        ACT_MAIN["MainActivity.kt & HomeScreen.kt\n(Dark Terminal UI, Pairing Card, Token Display)"]
        QR_SCAN["ui/QrScannerScreen.kt\n(CameraX Preview + ML Kit Barcode Analyzer HUD)"]
        THEME["ui/theme/ (Color.kt, Theme.kt)\n(Render-inspired Dark Palette)"]
        FCM_SVC["service/NotifFcmService.kt\n(FirebaseMessagingService Handler)"]
        NOTIF_HLP["service/NotificationHelper.kt\n(Progress & Completion Channels, Groups)"]
        DISMISS_RCV["service/NotificationDismissReceiver.kt\n(Swipe-away Dismissal Tracking)"]
        DATA_STORE["data/PairingDataStore.kt\n(Jetpack DataStore Pairing State & Flows)"]

        ACT_MAIN --> THEME
        ACT_MAIN --> NOTIF_HLP
        ACT_MAIN --> DATA_STORE
        ACT_MAIN --> QR_SCAN
        QR_SCAN --> DATA_STORE
        FCM_SVC --> NOTIF_HLP
        FCM_SVC --> DATA_STORE
        NOTIF_HLP --> DISMISS_RCV
    end

    subgraph ProductionDeployment["Oracle Cloud Infrastructure (Production VM)"]
        IPT["iptables / UFW\n(Ports 80 & 443 Netfilter)"]
        NGINX["nginx.conf\n(Rate Limit 30r/s, SSL Termination, HSTS, Gzip, WS)"]
        CERT["Certbot / Let's Encrypt\n(Auto-renewing TLS)"]
        SYS_SVC["systemd (notifs-api.service)\n(Docker Compose Daemon Orchestration)"]
        DKR["Docker Container (Python 3.12-slim)\n(Non-root appuser, Multi-worker Uvicorn, 127.0.0.1:8000)"]

        IPT --> NGINX
        CERT -.->|Certificates| NGINX
        SYS_SVC --> DKR
        NGINX -->|Reverse Proxy / HTTP 1.1| DKR
    end

    subgraph BackendServer["Server (FastAPI Engine & Tracker inside Container)"]
        MAIN["main.py\n(FastAPI App Factory, Lifespan, CORS)"]
        API_SAMPLES["api/samples.py\n(POST /v1/samples Endpoint with Bearer Auth)"]
        API_PAIRINGS["api/pairings.py\n(POST /v1/pairings, /claim, GET/DELETE /v1/pairings/{id})"]
        API_HEALTH["api/health.py\n(GET /health Endpoint)"]
        AUTH["auth.py\n(SHA-256 Secret Hash & Bearer Dependency)"]
        SCHEMAS["schemas.py\n(Schema v1 Pydantic Models & Pairing Contracts)"]
        CONFIG["config.py\n(Settings & Env Config)"]
        
        STORE_BASE["store/base.py\n(BasePairingStore ABC & PairingRecord)"]
        STORE_MEM["store/memory.py\n(InMemoryPairingStore with 5m TTL & Attempt Limit)"]
        STORE_FS["store/firestore.py\n(FirestorePairingStore)"]

        TRK_MGR["tracker/manager.py\n(TrackerManager, Multi-DL, Seq Counter)"]
        TRK_DL["tracker/download.py\n(TrackedDownload State Machine)"]
        TRK_CALC["tracker/calculator.py\n(SpeedSmoother EMA, ETA, Percentage)"]
        
        NOTIF_BASE["notifier/base.py\n(BaseNotifier ABC with target_token)"]
        NOTIF_CONSOLE["notifier/console.py\n(ANSI Developer Terminal Color Notifier)"]
        NOTIF_FCM["notifier/fcm.py\n(Firebase Admin High-Priority Data Notifier)"]
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
        TRK_MGR --> TRK_DL
        TRK_DL --> TRK_CALC
        TRK_MGR --> NOTIF_COMPOSITE
        NOTIF_COMPOSITE --> NOTIF_CONSOLE
        NOTIF_COMPOSITE --> NOTIF_FCM
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
        TLS_EXT["extension/test_poller.js\n(Extension Unit Suite)"]
        TEST_SRV["server/tests/\n(22 Pytest Suites for Server, Auth, Pairings & FCM)"]
    end

    POL -.->|Schema v1 Samples via HTTPS| NGINX
    POP -->|POST /v1/pairings via HTTPS| NGINX
    QR_SCAN -->|POST /v1/pairings/{code}/claim via HTTPS| NGINX
    STORE_FS -->|Firebase Admin SDK| FS_DB
    NOTIF_FCM -->|Firebase Admin SDK| FCM_SRV
    FCM_SRV -->|High-Priority Data Message| FCM_SVC
```

---

## 2. Implemented Modules & Responsibilities

| Module / Component | Path | Responsibility & Implemented State | Inter-module Connection |
|---|---|---|---|
| **Production Dockerfile** | `deploy/Dockerfile` | Multi-arch (ARM64 / x86_64) Python 3.12-slim container with non-root user `appuser`, built-in healthcheck, and multi-worker Uvicorn. | Builds backend image for Docker Compose. |
| **Docker Compose Orchestration** | `deploy/docker-compose.yml` | Isolated container running backend strictly bound to `127.0.0.1:8000`, read-only Firebase credential mounting, and JSON log rotation (`10m`, max 3 files). | Managed by systemd. |
| **Nginx Reverse Proxy & Security** | `deploy/nginx.conf` | SSL termination, HTTP $\rightarrow$ HTTPS redirection, rate limiting (`30 req/s`, burst 20), WebSocket upgrade headers, HSTS, Gzip compression, and security headers. | Fronts all client HTTPS traffic on ports 80/443. |
| **Systemd Service Unit** | `deploy/systemd/notifs-api.service` | Production OS service manager with auto-restart (`RestartSec=5s`), process isolation, and journald logging. | Auto-launches Docker Compose at boot. |
| **Automated Setup Script** | `deploy/oracle-setup.sh` | Turnkey provisioning script automating OS updates, iptables/UFW firewall unblocking, Docker installation, directory creation (`/opt/notifs`), and initial ACME challenge proxy. | One-command setup on Oracle Cloud Ubuntu VM. |
| **Firestore Security Rules** | `deploy/firestore.rules` | Restricts client reads/writes (`allow read, write: if false;`), reserving access exclusively to the server via Admin SDK. | Deployed to Firebase Console. |
| **Production Deployment Guide** | `deploy/docs/oracle-deploy.md` | Comprehensive step-by-step walkthrough covering VM creation, VCN security rules, DNS setup, SSL issuance, and client connection. | Reference for deployment & operations. |
| **Pairing API Endpoints** | `server/api/pairings.py` | Generates 6-character claim codes, hashed secrets (`POST /v1/pairings`), validates and claims device tokens (`POST /v1/pairings/{code}/claim`), returns pairing status (`GET /v1/pairings/{id}`), and unpairs (`DELETE /v1/pairings/{id}`). | Backed by `BasePairingStore` and authenticated via `auth.py`. |
| **Pairing Storage Backends** | `server/store/` | `InMemoryPairingStore` (thread-safe RAM with 5-minute TTL and 5-attempt limit) and `FirestorePairingStore` (cloud-persisted Google Cloud Firestore collection). | Consumed by `pairings.py` and `auth.py`. |
| **Bearer Authentication** | `server/auth.py` | SHA-256 secret hashing and FastAPI dependency extracting Bearer tokens, looking up active claimed pairings, and routing dynamic FCM tokens to the notifier. | Guards `/v1/samples` and `/v1/pairings/{id}`. |
| **FCM Notifier Backend** | `server/notifier/fcm.py` | Uses Firebase Admin SDK to dispatch high-priority data messages (`priority="high"`, `ttl=30s`) targeting paired mobile devices dynamically. | Invoked by `TrackerManager` / `CompositeNotifier`. |
| **Composite Notifier** | `server/notifier/composite.py` | Multiplexes notifications to both `ConsoleNotifier` and `FCMNotifier` concurrently so terminal logging and mobile pushes run simultaneously. | Used as active notifier in `main.py` lifespan. |
| **Chrome Extension QR Generator & UI** | `extension/popup/` | Offline canvas QR code renderer (`qrcode.js`), live QR modal with 6-character code and 5m countdown, automatic claim detection polling, and persistent paired/unpaired view switching. | Interacts with `/v1/pairings` on server. |
| **Android QR Scanner** | `android/.../ui/QrScannerScreen.kt` | CameraX live preview with ML Kit Barcode Analyzer, terminal HUD crosshair viewfinder, automatic JSON QR parsing, and immediate claim dispatching via OkHttp. | Claims pairing on backend and updates `PairingDataStore`. |
| **Android Pairing Data Store** | `android/.../data/PairingDataStore.kt` | Manages persistent pairing state (`pairingId`, `serverUrl`, `pcName`, `isPaired`) via Jetpack DataStore preferences and exposed StateFlows. | Powers `HomeScreen.kt` and `QrScannerScreen.kt`. |
| **Server Engine** | `server/` | FastAPI service with speed smoothing, ETA math, finite state machine, Bearer authentication, and dual Console + FCM dispatch. | Ingests from Extension, outputs to Console & FCM. |
| **Testing Tools** | `tools/` | `sample_replay.py`, `fcm_test_sender.py`, `test_poller.js`, and 22 Pytest unit & integration suites. | 100% automated test coverage. |

---

## 3. Communication Contracts Active

- **Sample Ingestion**: Defined in `docs/protocol.md#1` (`POST /v1/samples` with `Authorization: Bearer <secret>`).
- **Pairing Handshake**: Defined in `docs/protocol.md#4` (`POST /v1/pairings` $\rightarrow$ QR Code $\rightarrow$ `POST /v1/pairings/{code}/claim`).
- **Health Check**: `GET /health` returning `{"status": "ok", "version": "0.1.0", "timestamp": "..."}`.
- **FCM Data Delivery**: Defined in `docs/protocol.md#2` (high-priority FCM data message).
- **LAN WebSocket**: Defined in `docs/protocol.md#3` (`/v1/ws`).

---

## 4. Design System & Theme Tokens (Render-inspired Dark Terminal)

Applied across Chrome Extension, Server Terminal Logs, Android Native UI, and Notifications:

| Token | Hex / Value | Usage |
|---|---|---|
| `--bg-canvas` | `#09090c` / `#000000` | Deep terminal black background |
| `--bg-card` | `#111116` / `#141419` | Surface containers & cards |
| `--border-subtle` | `#23232c` | Minimalist dark borders |
| `--purple-brand` | `#8a05ff` | Primary action accent, focus glow, badge outlines, sequence tags |
| `--purple-light` | `#c084fc` | Command flag prefixes, ETA text, completed download state |
| `--green-neon` | `#61cf92` | Active download state, pulsing status LED, speed highlights, online pills, QR viewfinder |
| `--text-white` | `#ffffff` | Primary titles, filenames, terminal commands |
| `--text-dim` | `#a1a1aa` | Secondary stats, labels, progress details |
| `--text-muted` | `#52525b` | Comments, inactive indicators, timestamps |
| **Typography** | `Monospace / Code` | `ui-monospace, "JetBrains Mono", Menlo, Consolas` |
| **Iconography** | `11x11 Pixel Grid` | Custom pixel-matrix block glyphs ([`icon.png`](file:///d:/1shav/1shav.code/projects/notifs/icon.png)) |
