# CLAUDE.md — How's My Download (HMD)

Monorepo that mirrors Chrome download progress to Android notifications.
Flow: Chrome extension polls `chrome.downloads` every 2s → `POST /v1/samples` (bearer auth, filenames AES-GCM encrypted client-side) → FastAPI server computes speed/ETA, throttles → FCM high-priority **data** message → Android `NotifFcmService` decrypts filename and renders notifications.

Built from `implementation_plan.md` (phases 0–10; **phase 9 LAN mode was skipped**). `current_build.md` is a status doc written during the build and over-describes some things — trust the code over it.

## Layout

| Path | What |
|---|---|
| `server/` | FastAPI app. Package is `server` (pyproject maps `server` → `.`), so imports are `from server.x import y` and must be run with the repo root on `PYTHONPATH`. |
| `server/main.py` | App factory + `lifespan` that wires store, notifier, throttler, tracker into `app.state`. Payload-size middleware (Content-Length only). |
| `server/api/` | `samples.py` (ingest), `pairings.py` (create/claim/status/delete/token refresh/rotate-secret), `health.py` |
| `server/tracker/` | `download.py` per-download state machine, `calculator.py` EMA speed/ETA, `manager.py` keyed by `(pairing_id, download_id)` |
| `server/throttler/push_throttler.py` | 2s per-pairing coalescing, state-change bypass, owns the `seq` counter |
| `server/notifier/` | `BaseNotifier`, `console`, `fcm`, `composite` (console+fcm). No LAN notifier. |
| `server/store/` | `BasePairingStore`, `memory`, `firestore` (sync client wrapped in `asyncio.to_thread`). `SQLITE_PATH` in config is unused — no sqlite store exists. |
| `extension/` | MV3, plain ES modules, no build step, no deps. `background/{service-worker,poller,api,crypto}.js`, `popup/` (incl. vendored `qrcode.js`). |
| `android/` | Kotlin + Compose, single module `app`, package `com.notifs.app`. Most UI lives in `MainActivity.kt` (~900 lines). |
| `deploy/` | Dockerfile, docker-compose, nginx.conf, systemd unit, `oracle-setup.sh`, Firestore rules |
| `tools/` | `sample_replay.py` (+ `sample_traces/`), `fcm_test_sender.py`, `package_extension.py` (→ `dist/`), icon scripts |
| `docs/` | `protocol.md` (schema v1), `ADR-0001-architecture.md`, `metrics.md`, `store-listing.md` |

## Commands

```bash
# Server (from repo root; venv at .venv)
pip install -e "./server[dev]"
cd server && ruff check . && pytest            # pytest config sets pythonpath=".."
uvicorn server.main:app --reload --port 8000    # from repo root; NOTIFIER_TYPE=console, STORE_TYPE=memory by default

# Replay a recorded trace against a local server
python tools/sample_replay.py tools/sample_traces/ubuntu_download_trace.json

# Extension tests (Node 22, no npm install needed)
cd extension && node --test test_poller.js test_crypto.js test_api.js   # test_fake_chrome.js stubs chrome.* / fetch

# Android (needs android/app/google-services.json; CI copies the .example if absent)
cd android && ./gradlew testDebugUnitTest assembleDebug

# Package extension zip
python tools/package_extension.py
```

CI (`.github/workflows/ci.yml`) runs exactly the three blocks above on push/PR to master.

## Config (env vars, `server/config.py`)

`NOTIFIER_TYPE` = `console` (default) | `fcm`/`both`/`multi` (console+FCM). `STORE_TYPE` = `memory` (default) | `firestore`. `GOOGLE_APPLICATION_CREDENTIALS` = service account path. `FCM_TOKEN`/`TEST_FCM_TOKEN` = dev fallback token. Production compose sets `firestore` + `fcm`.

## Protocol invariants (see `docs/protocol.md`, which is kept in sync with the code)

- States: `starting|downloading|paused|completed|failed|erased` (+ `stale` exists in the enum but is never emitted server-side).
- Encryption: `enc:v1:<b64 iv(12B)>:<b64 ciphertext+tag>` for `filename` and `mime_type`. Key is 32 random bytes as hex, generated in `popup.js`, delivered to the phone **only** inside the QR JSON `{server_url, code, pc_name, enc_key}`. Never send it to the server. Encryption **fails closed** (`prepareWirePayload` in `api.js` throws; sample is dropped).
- Two credentials per pairing, stored as SHA-256 hashes: extension secret (samples, rotate) and device secret (issued at claim; FCM token refresh). Both can unpair/read status. Pairing-scoped routes go through `get_pairing_actor` in `server/auth.py`; unknown pairing and wrong secret both return 401.
- FCM data payload: string map with `seq`, `epoch` (server boot ms), `sent_at`, `source`, `pc_name`, `pairing_id`, `downloads` (compact JSON, no `mime_type`, no nulls), and `omitted` when trimmed. `build_data_payload` in `notifier/fcm.py` keeps it under 3584 bytes (FCM limit 4096).
- Phone ordering lives in `android/.../service/SequenceGate.kt`: drop other pairings, compare `seq` only within one `epoch`, new epoch = new stream.
- Pairings are purged on FCM errors only when the token is dead (`is_dead_token_error`), never for message-level errors.
- The extension clears credentials on 401 **unless** the stored secret changed while the request was in flight (rotation race).

## Known gaps / gotchas (verified in code, Oct 2026)

- Tracker, throttler `seq`/`epoch`, and rate limiters are in-process memory: the server **must** run one Uvicorn worker (Dockerfile pins `--workers 1`).
- The throttler holds its lock while awaiting the FCM send, so one slow send delays every pairing.
- Auth does a Firestore query per sample (no cache). The Firestore transactional claim path has no automated test (needs the emulator).
- Pairings made before device secrets existed cannot refresh their FCM token or unpair from the phone; re-pair.
- Android: the enc key and device secret are in Preferences DataStore (app-private, backup disabled) but not Keystore-wrapped. The 90s "PC offline" safety net is a coroutine in the FCM service scope, which can die with the process (`setTimeoutAfter` would be sturdier).
- Cleartext HTTP and user CAs are allowed only in debug builds (`app/src/debug/res/xml/network_security_config.xml`); release is HTTPS + system CAs.
- README/metrics claims the code does not back up: "100% coverage" (no coverage tooling), the numbers in `docs/metrics.md` (no instrumentation in the repo produces them), MIT license (no LICENSE file). README repo links point to `1shav/hows-my-download`; the real remote is `W0NB0N/How-sMyDownload`.

## Conventions

- Python: ruff (line length 100, rules E/F/I/UP/B/SIM), Pydantic v2 models in `schemas.py`, async everywhere, store/notifier behind ABCs. New tests go in `server/tests/` using fixtures in `conftest.py`.
- Extension: no bundler; keep zero dependencies. Logs are prefixed `[How's My Download]`.
- UI style on both clients is a dark "terminal" theme (purple `#8a05ff`, green `#61cf92`, monospace). Tokens are listed in `current_build.md` §5.
- Never commit `google-services.json`, `service-account.json`, or `.env`. `commands.txt` (SSH/deploy notes) is local only.
