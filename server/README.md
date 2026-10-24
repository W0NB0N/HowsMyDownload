# How's My Download: server

FastAPI service that authenticates samples from the browser extension, computes speed and ETA, throttles and orders pushes, sends them to the phone over FCM, and queues the phone's pause/resume/restart commands for the extension.

```bash
# from the repository root
pip install -e "./server[dev]"
uvicorn server.main:app --reload --port 8000     # console notifier + in-memory store
cd server && ruff check . && pytest --cov
```

| Module | Role |
|---|---|
| `main.py` | App factory, lifespan wiring, 50 KB body limit |
| `api/` | `samples` (ingest), `pairings` (create/claim/status/token/rotate/unpair), `commands` (phone → PC), `health` |
| `auth.py` | Extension and device bearer secrets (SHA-256 hashed), per-pairing actor resolution |
| `tracker/` | Per-download state machine, EMA speed, ETA |
| `throttler/` | ≤ 1 push / 2 s per pairing, state-change bypass, `(epoch, seq)` ordering |
| `commands/` | In-memory command queue with expiry |
| `notifier/` | FCM (4 KB-budgeted data messages), console, composite |
| `store/` | Firestore (transactional claim, TTL cleanup), in-memory, 30 s read-through cache |

Configuration is via environment variables (`server/config.py`): `STORE_TYPE` (`memory` | `firestore`), `NOTIFIER_TYPE` (`console` | `fcm`), `GOOGLE_APPLICATION_CREDENTIALS`. The server must run as **one** worker; see the [Dockerfile](../deploy/Dockerfile).

Wire format: [`docs/protocol.md`](../docs/protocol.md). Deployment: [`docs/self-hosting.md`](../docs/self-hosting.md).
