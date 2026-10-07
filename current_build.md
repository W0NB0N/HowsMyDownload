# Current Build Status & Architecture Topology

*Last Updated: Phase 0 Completion*

---

## 1. Abstracted Module Graph

```mermaid
graph TD
    subgraph RepoLayout["Project Monorepo"]
        DOCS["docs/\n- protocol.md (Schema v1)\n- ADR-0001-architecture.md"]
        EXT["extension/\n- manifest.json (MV3)\n- background/service-worker.js\n- popup/ (HTML/CSS/JS)"]
        SRV["server/\n- pyproject.toml\n- __init__.py\n- [FastAPI + uv venv ready]"]
        AND["android/\n- Gradle build setup (AGP 8.7, Kotlin 2.0)\n- AndroidManifest.xml\n- MainActivity.kt (Compose Shell)"]
        DEP["deploy/\n- Dockerfile\n- nginx.conf\n- docker-compose.yml\n- notifs-api.service"]
        TLS["tools/\n- sample_replay.py\n- fcm_test_sender.py"]
    end
```

---

## 2. Implemented Modules & Responsibilities

| Module / Component | Path | Responsibility & Implemented State | Inter-module Connection |
|---|---|---|---|
| **Protocol Spec** | `docs/protocol.md` | Schema v1 defining contracts for `POST /v1/samples`, FCM data payload, LAN frames, and pairing handshake. | Authoritative source of truth for Extension, Server, and Android. |
| **Architecture Decision** | `docs/ADR-0001-architecture.md` | Documents rationale for Oracle VM, FCM data messages, and transport abstraction. | High-level system design guidelines. |
| **Chrome Extension (Scaffold)** | `extension/` | Manifest V3 configuration with `downloads`, `alarms`, `storage` permissions; initial popup UI and background service worker entry point. | Communicates to `server` via HTTP `POST /v1/samples`. |
| **Server Backend (Scaffold)** | `server/` | Python 3.11+ project definition (`pyproject.toml`) with FastAPI, Pydantic v2, Firebase Admin, WebSockets, Ruff, Pytest installed in `.venv`. | Ingests from `extension`, relays to `Firebase FCM` / `Android`. |
| **Android Client (Scaffold)** | `android/` | Gradle multiplatform configuration with Material 3 Compose, CameraX, ML Kit, Firebase Messaging dependencies, and basic `MainActivity`. | Ingests from `Firebase FCM` / `LAN WebSocket`. |
| **Deployment Engine** | `deploy/` | Production `Dockerfile`, `nginx.conf` (SSL + WebSocket proxying), systemd service definition, and `docker-compose.yml` (self-hosting). | Hosts and exposes `server`. |
| **Developer Tools** | `tools/` | `sample_replay.py` (simulates client sample batches) and `fcm_test_sender.py` (simulates server-to-phone FCM pushes). | Used for isolated verification of Server & Android app. |

---

## 3. Communication Contracts Active

- **Sample Ingestion**: Defined in `docs/protocol.md#1` (`POST /v1/samples`).
- **FCM Data Delivery**: Defined in `docs/protocol.md#2` (high-priority FCM data message).
- **LAN WebSocket**: Defined in `docs/protocol.md#3` (`/v1/ws`).
- **Pairing**: Defined in `docs/protocol.md#4` (ephemeral 6-digit code + hash-stored bearer secret).
