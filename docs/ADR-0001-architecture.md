# ADR-0001: System Architecture and Transport Decisions

## Status
Accepted

## Context
The goal of the Download Notifs project is to mirror real-time download progress from a user's desktop computer to their Android device via system notifications without draining the phone battery or depending on foreground apps being kept active.

Key constraints & requirements:
1. Low latency updates during active transfers (~2s update rate).
2. Battery efficiency on mobile when idle or screen is locked.
3. Zero cost / deterministic hosting (avoiding bill shocks from cloud platform invocations).
4. Extensible source model (initially Chrome browser downloads, later torrents, gaming clients, etc.).
5. Ability to switch to direct LAN transport when both devices share local WiFi.

## Decisions

### 1. Cloud Backend & Hosting: Oracle Cloud Always-Free ARM VM
- **Decision:** Deploy the FastAPI backend on an Oracle Cloud Infrastructure (OCI) Always-Free Ampere ARM instance (`VM.Standard.A1.Flex`) with Ubuntu, Nginx, and systemd.
- **Rationale:** Free-tier PaaS offerings (e.g. Render) spin down on inactivity, causing 30-60s cold-start delays when downloads begin. Cloud Run presents variable cost risks once free limits are exceeded. Oracle's Always-Free tier provides a dedicated, continuously running server with 2 OCPUs and 12 GB RAM with $0 recurring cost.

### 2. Mobile Delivery: FCM Data Messages
- **Decision:** Use Firebase Cloud Messaging (FCM) high-priority **data messages** as the remote transport.
- **Rationale:** Android Doze mode and App Standby restrict background network requests and persistent sockets. FCM is the single multiplexed channel maintained natively by Google Play Services, waking the app for milliseconds to render/update system progress notifications without persistent foreground service battery drain.

### 3. Rate-Limiting & Throttling
- **Decision:** Implement a 2–3s server-side push throttle with state-change bypass.
- **Rationale:** Continuous progress updates do not need to exceed 2-3s intervals. However, discrete state changes (e.g., `paused`, `completed`, `failed`) bypass the throttle window to immediately update or dismiss the notification.

### 4. Storage & State Abstraction: `PairingStore` Interface
- **Decision:** Define a `PairingStore` interface supporting Firestore (production cloud), SQLite (self-hosted), and an in-memory implementation (unit testing).
- **Rationale:** Decouples the backend logic from the specific database persistence mechanism.

### 5. Transport Abstraction: `Notifier` Interface
- **Decision:** Define a `Notifier` interface with `FCMNotifier`, `LanNotifier`, and `ConsoleNotifier`.
- **Rationale:** Allows local development and testing without live FCM tokens, and enables seamless routing between LAN WebSocket transport and cloud FCM transport.

### 6. Client Pairing and Authentication
- **Decision:** Ephemeral short-code pairing via QR code. Extension produces a bearer secret; the server stores only `hash(secret)`. Phone claims code with its FCM device token.
- **Rationale:** Eliminates the need for user accounts/passwords while securing the `/v1/samples` endpoint against unauthorized push spam.

## Consequences
- Requires an initial one-time VM and Nginx setup.
- Android app requires `POST_NOTIFICATIONS` permission and Google Play Services for FCM.
- LAN mode requires self-signed certificate generation and fingerprint pinning on Android to comply with Android Network Security Config.

## Outcome (October 2026)

What was built differs from the plan above in three places:

- **Stores (decision 4):** `memory` and `firestore` exist, plus a read-through cache in front of Firestore. **SQLite was not built.** Self-hosters use their own Firestore (free tier), see [`self-hosting.md`](self-hosting.md).
- **Transports (decision 5):** `ConsoleNotifier`, `FCMNotifier` and a composite exist. **`LanNotifier` and LAN mode were dropped.** Keeping a socket alive on Android needs a foreground service and fails under Doze; [`metrics.md`](metrics.md#5-architectural-analysis-fcm-vs-lan-mode) has the comparison.
- **Direction of control:** the system is no longer one-way. The phone can pause, resume and restart downloads through a command queue on the server, which the extension drains from its sample responses ([`protocol.md` §5](protocol.md#5-download-commands-phone--server--extension)).

Decisions 1–3 and 6 held. The measured end-to-end figures are in [`metrics.md`](metrics.md).
