# 📲 Download Notifs

Real-time Chrome download progress mirrored to your Android phone via lock-screen notifications and Firebase Cloud Messaging (FCM).

---

## Architecture Overview

```
[ Chrome Browser ] ➔ [ Chrome Extension ]
                             │ (POST /v1/samples every 2s)
                             ▼
                 [ FastAPI Server on Oracle VM ]
                             │ (FCM Data Push)
                             ▼
              [ Google Firebase Cloud Messaging ]
                             │
                             ▼
              [ Android Native Notification ]
```

## Repository Structure

```
├── extension/       # Manifest V3 Chrome extension
├── server/          # Python FastAPI computation backend & pairing engine
├── android/         # Jetpack Compose native Android app
├── deploy/          # Dockerfile, Nginx config, systemd service, deployment scripts
├── docs/            # ADRs, Protocol specification (Schema v1)
└── tools/           # Replay and FCM test scripts
```

## Quick Start (Development)

### 1. Server
```bash
uv venv .venv
# Activate virtualenv (.venv\Scripts\activate on Windows or source .venv/bin/activate on Linux)
uv pip install -e "./server[dev]"
uvicorn server.main:app --reload
```

### 2. Extension
1. Open Chrome and navigate to `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select the `/extension` directory.

### 3. Android App
1. Open `/android` in Android Studio.
2. Place your `google-services.json` in `android/app/`.
3. Build & Run on an Android device running Android 8.0+ (API 26+).

---

## Documentation
- [Protocol Specification (Schema v1)](docs/protocol.md)
- [ADR-0001: Architecture & Decisions](docs/ADR-0001-architecture.md)
