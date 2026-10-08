# Current Build Status & Architecture Topology

*Last Updated: Phase 3 Completion (Android App Standalone + FCM)*

---

## 1. Abstracted Module Graph

```mermaid
graph TD
    subgraph ChromeExtension["Chrome Extension (Manifest V3)"]
        SW["service-worker.js\n(Lifecycle & Event Multiplexer)"]
        POL["poller.js\n(Downloads Observer, 2s Tick, Keepalive Alarm)"]
        API["api.js\n(Sample Dispatcher & Trace Recorder)"]
        POP["popup/ (HTML, CSS, JS)\n(Live Monitor & Trace Exporter)"]
        
        SW --> POL
        POL --> API
        API -->|Broadcasts SAMPLE_DISPATCHED| POP
        POP -->|Triggers POLL_NOW / Settings| SW
    end

    subgraph BackendServer["Server (FastAPI Engine & Tracker)"]
        MAIN["main.py\n(FastAPI App Factory, Lifespan, CORS)"]
        API_SAMPLES["api/samples.py\n(POST /v1/samples Endpoint)"]
        API_HEALTH["api/health.py\n(GET /health Endpoint)"]
        SCHEMAS["schemas.py\n(Schema v1 Pydantic Models)"]
        CONFIG["config.py\n(Settings & Env Config)"]
        
        TRK_MGR["tracker/manager.py\n(TrackerManager, Multi-DL, Seq Counter)"]
        TRK_DL["tracker/download.py\n(TrackedDownload State Machine)"]
        TRK_CALC["tracker/calculator.py\n(SpeedSmoother EMA, ETA, Percentage)"]
        
        NOTIF_BASE["notifier/base.py\n(BaseNotifier ABC)"]
        NOTIF_CONSOLE["notifier/console.py\n(ANSI Developer Terminal Color Notifier)"]

        MAIN --> API_SAMPLES
        MAIN --> API_HEALTH
        API_SAMPLES --> TRK_MGR
        TRK_MGR --> TRK_DL
        TRK_DL --> TRK_CALC
        TRK_MGR --> NOTIF_CONSOLE
        NOTIF_CONSOLE -.->|Implements| NOTIF_BASE
    end

    subgraph AndroidClient["Android Client (Kotlin / Compose)"]
        ACT_MAIN["MainActivity.kt & HomeScreen.kt\n(Dark Terminal UI, Token Display, Diagnostics)"]
        THEME["ui/theme/ (Color.kt, Theme.kt)\n(Render-inspired Dark Palette)"]
        FCM_SVC["service/NotifFcmService.kt\n(FirebaseMessagingService Handler)"]
        NOTIF_HLP["service/NotificationHelper.kt\n(Progress & Completion Channels, Groups)"]
        DISMISS_RCV["service/NotificationDismissReceiver.kt\n(Swipe-away Dismissal Tracking)"]
        DATA_STORE["data/PairingDataStore.kt\n(Jetpack DataStore Preferences)"]

        ACT_MAIN --> THEME
        ACT_MAIN --> NOTIF_HLP
        ACT_MAIN --> DATA_STORE
        FCM_SVC --> NOTIF_HLP
        FCM_SVC --> DATA_STORE
        NOTIF_HLP --> DISMISS_RCV
    end

    subgraph FirebaseCloud["Google Firebase Cloud Messaging"]
        FCM_SRV["Firebase Cloud Messaging (FCM)"]
    end

    subgraph Deployment["Deployment & DevOps"]
        DEP_CONF["Dockerfile, nginx.conf, systemd, docker-compose.yml"]
    end

    subgraph DevTools["Testing & Verification Tools"]
        TLS_REPLAY["tools/sample_replay.py\n(Sample Stream Replayer)"]
        TLS_FCM["tools/fcm_test_sender.py\n(FCM Test Stream Pusher)"]
        TLS_EXT["extension/test_poller.js\n(Extension Unit Suite)"]
        TEST_SRV["server/tests/\n(10 Pytest Suites for Server)"]
    end

    POL -.->|Schema v1 Samples| API
    POP -.->|Exported JSON Traces| TLS_REPLAY
    TLS_REPLAY -->|POST /v1/samples| API_SAMPLES
    TLS_FCM -->|Firebase Admin SDK| FCM_SRV
    FCM_SRV -->|High-Priority Data Message| FCM_SVC
```

---

## 2. Implemented Modules & Responsibilities

| Module / Component | Path | Responsibility & Implemented State | Inter-module Connection |
|---|---|---|---|
| **Android Main Activity & Screen** | `android/.../MainActivity.kt` | Jetpack Compose developer UI. Displays live FCM device token with copy action, manages `POST_NOTIFICATIONS` permission prompt, and provides local test notification triggers. | Coordinates `NotificationHelper` and `PairingDataStore`. |
| **Android Notification Helper** | `android/.../service/NotificationHelper.kt` | Manages notification channels (`downloads` low importance silent, `completions` default audible), builds live progress notifications with speed/ETA/percentage, completion alerts, and multi-download group summaries. | Invoked by `NotifFcmService` and `MainActivity`. |
| **Android FCM Service** | `android/.../service/NotifFcmService.kt` | Background `FirebaseMessagingService`. Ingests FCM data messages, parses downloads JSON, checks sequence ordering, filters dismissed transfers, and routes to `NotificationHelper`. | Wires Google Play Services FCM to Android Notification system. |
| **Notification Dismiss Receiver** | `android/.../service/NotificationDismissReceiver.kt` | Broadcast receiver capturing notification swipe-away `deleteIntent` to prevent unwanted re-posts. | Records dismissal in `PairingDataStore`. |
| **Android Data Store** | `android/.../data/PairingDataStore.kt` | Local preference management using AndroidX DataStore for FCM tokens, last processed sequence numbers, and dismissed download IDs. | Consumed by `NotifFcmService` and `MainActivity`. |
| **Android Terminal Theme** | `android/.../ui/theme/` | Material 3 Dark theme implementing Render-inspired color palette (`#09090c`, `#8a05ff`, `#61cf92`, `#c084fc`) with monospace typography. | Styles all Android Compose UI components. |
| **FCM Push Testing Tool** | `tools/fcm_test_sender.py` | Python test tool simulating live FCM push streams directly to physical devices. Supports `--mode normal`, `stall`, `pause`, `fail`, `multi`. | Validates Android FCM reception in isolation. |
| **Server Engine** | `server/` | FastAPI backend with speed smoothing, ETA math, finite state machine, and console telemetry. | Standalone ingest and processing brain. |
| **Chrome Extension** | `extension/` | Chrome download monitor with 2s polling, keepalive alarms, and terminal popup. | Standalone source collector. |

---

## 3. Communication Contracts Active

- **Sample Ingestion**: Defined in `docs/protocol.md#1` (`POST /v1/samples`).
- **FCM Data Delivery**: Defined in `docs/protocol.md#2` (high-priority FCM data message).
- **LAN WebSocket**: Defined in `docs/protocol.md#3` (`/v1/ws`).
- **Pairing**: Defined in `docs/protocol.md#4` (ephemeral 6-digit code + hash-stored bearer secret).

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
| `--green-neon` | `#61cf92` | Active download state, pulsing status LED, speed highlights |
| `--text-white` | `#ffffff` | Primary titles, filenames, terminal commands |
| `--text-dim` | `#a1a1aa` | Secondary stats, labels, progress details |
| `--text-muted` | `#52525b` | Comments, inactive indicators, timestamps |
| **Typography** | `Monospace / Code` | `ui-monospace, "JetBrains Mono", Menlo, Consolas` |
| **Iconography** | `11x11 Pixel Grid` | Custom pixel-matrix block glyphs ([`icon.png`](file:///d:/1shav/1shav.code/projects/notifs/icon.png)) |
