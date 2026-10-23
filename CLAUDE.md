# CLAUDE.md — How's My Download (HMD)

Monorepo that mirrors Chrome download progress to Android notifications.
Flow: Chrome extension polls `chrome.downloads` every 2s → `POST /v1/samples` (bearer auth, filenames AES-GCM encrypted client-side) → FastAPI server computes speed/ETA, throttles → FCM high-priority **data** message → Android `NotifFcmService` decrypts filename and renders notifications.

Built from `implementation_plan.md` (phases 0–10; **phase 9 LAN mode was skipped**). `implementation_plan.md`, `current_build.md` and `phases.txt` are local-only planning notes (gitignored); they over-describe some things, so trust the code over them.

## Layout

| Path | What |
|---|---|
| `server/` | FastAPI app. Package is `server` (pyproject maps `server` → `.`), so imports are `from server.x import y` and must be run with the repo root on `PYTHONPATH`. |
| `server/main.py` | App factory + `lifespan` that wires store, notifier, throttler, tracker into `app.state`. `BodySizeLimitMiddleware` (50 KB, also for chunked bodies). Firestore store is wrapped in `CachedPairingStore`. |
| `server/api/` | `samples.py` (ingest; response hands over queued commands), `pairings.py` (create/claim/status/delete/token refresh/rotate-secret), `commands.py` (phone→PC pause/resume/restart + expiry sweeper), `health.py` |
| `server/commands/queue.py` | In-memory `CommandQueue`: one pending command per download, 75s TTL, at-most-once `drain` |
| `server/tracker/` | `download.py` per-download state machine, `calculator.py` EMA speed/ETA, `manager.py` keyed by `(pairing_id, download_id)` |
| `server/throttler/push_throttler.py` | 2s per-pairing coalescing, state-change bypass, owns `seq` + `epoch`. State under `_lock`; sends outside it under a per-pairing FIFO send lock |
| `server/notifier/` | `BaseNotifier`, `console`, `fcm`, `composite` (console+fcm). No LAN notifier. |
| `server/store/` | `BasePairingStore` + shared `apply_claim`, `memory`, `firestore` (sync client in `asyncio.to_thread`, transactional claim, `purge_at` TTL field on unclaimed docs, injectable client), `cached` (30s read-through cache; writes invalidate before and after) |
| `extension/` | MV3, plain ES modules, no build step, no deps. `background/{service-worker,poller,api,crypto,commands}.js`, `popup/` (incl. vendored `qrcode.js`). `tools/package_extension.py` ships everything under `background/` and `popup/` plus PNG icons, and fails if a file the manifest names is missing. |
| `android/` | Kotlin + Compose, single module `app`, package `com.notifs.app`. Most UI lives in `MainActivity.kt` (~1000 lines). Commands: `service/DownloadCommands.kt` (actions per state, send, error text), `service/CommandReceiver.kt` (notification buttons). |
| `deploy/` | Dockerfile, docker-compose, nginx.conf, systemd unit, `oracle-setup.sh` (copies the repo into `/opt/notifs`: update = pull in the clone, `cp -r server deploy /opt/notifs/`, rebuild), Firestore rules |
| `tools/` | `sample_replay.py` (+ `sample_traces/`; creates a throwaway pairing if no `--token`), `fcm_test_sender.py`, `package_extension.py` (→ `dist/`), `check_google_services.py` (used by the release workflow), `bench_server.py`, measurement: `measure_rtt.py`, `clock_offsets.py`, `latency_report.py --offset-ms` (parses `HMD_LATENCY` logcat), `measure_command_loop.py` (adb-driven pause/resume timing); `firestore-emulator/firebase.json`, icon scripts (source art in `assets/`) |
| `docs/` | `protocol.md` (schema v1), `metrics.md` (measured numbers + methods), `self-hosting.md`, `ADR-0001-architecture.md` (+ outcome addendum), `design.md` (theme tokens), `store-listing.md`, `images/` (README screenshots) |

## Commands

```bash
# Server (from repo root; venv at .venv)
pip install -e "./server[dev]"
cd server && ruff check . && pytest --cov     # pytest config sets pythonpath=".."

# Firestore store against the emulator (Java 11+; firebase-tools 13.29.x is broken, use 13.35.1)
npx -y firebase-tools@13.35.1 emulators:exec --only firestore --project demo-hmd \
  --config tools/firestore-emulator/firebase.json "cd server && pytest tests/test_firestore_emulator.py -o addopts="
# On Windows the emulator's java process outlives the command: stop whatever holds port 8085.
uvicorn server.main:app --reload --port 8000    # from repo root; NOTIFIER_TYPE=console, STORE_TYPE=memory by default

# Replay a recorded trace against a local server
python tools/sample_replay.py tools/sample_traces/ubuntu_download_trace.json

# Extension tests (Node 22, no npm install needed)
cd extension && node --test test_poller.js test_crypto.js test_api.js test_commands.js   # test_fake_chrome.js stubs chrome.* / fetch

# Android (needs android/app/google-services.json; CI copies the .example if absent)
cd android && ./gradlew testDebugUnitTest assembleDebug

# Package extension zip
python tools/package_extension.py
```

CI (`.github/workflows/ci.yml`) runs server (ruff + pytest --cov), the Firestore emulator suite, Android and extension tests on push/PR to master. `.github/workflows/release.yml` (manual or `v*` tag) builds a signed APK + extension zip from secrets `GOOGLE_SERVICES_JSON`, `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`; a tag must equal the app and extension versions.

Android build settings (`-P` or env, see top of `android/app/build.gradle.kts`): `hmd.applicationId`/`HMD_APPLICATION_ID`, `hmd.defaultServerUrl`/`HMD_SERVER_URL` (→ `BuildConfig.DEFAULT_SERVER_URL`, used for typed-code pairing), `hmd.keystoreFile`/`HMD_KEYSTORE_FILE` (+ password/alias/key password). Without a keystore, release builds are unsigned.

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
- Commands (protocol §5): device secret sends, extension secret collects/reports. Delivered on the samples response while transferring, else by the extension's command watch (3s for 10 min after activity, then a 30s alarm) while something is paused or failed <1h ago. Only failures are pushed back (`command_result` FCM event, fixed error codes, no `seq`). Restart = cancel + re-download the original URL + erase the old entry, reported once as `erased`.

## Known gaps / gotchas (verified in code, Oct 2026)

- `STORE_TYPE=memory` loses pairings on restart (extension gets 401 and unpairs). To test restart continuity locally, use `STORE_TYPE=firestore`.
- Tracker, throttler `seq`/`epoch`, rate limiters, the command queue, and the auth cache are in-process memory: the server **must** run one Uvicorn worker (Dockerfile pins `--workers 1`).
- Speed uses only sample (PC-clock) timestamps; idle cleanup uses the server's `time.monotonic()`. Don't mix the two clocks.
- An illegal state transition from the source resets the tracked download instead of raising (the extension would otherwise retry a 500 forever).
- The Firestore TTL policy on `pairings.purge_at` must be enabled in the console (deploy guide step 6.4).
- Pairings made before device secrets existed cannot refresh their FCM token or unpair from the phone; the app shows a re-pair warning.
- Android secrets (filename key, device secret) are AES-GCM wrapped with the AndroidKeyStore key `hmd_datastore_v1` (`util/SecretCipher.kt`); plaintext values from older builds migrate on first read.
- "PC offline" is an `AlarmManager` alarm (`service/StaleWatchdog.kt`), not a coroutine: exact when `SCHEDULE_EXACT_ALARM` is granted, else inexact and possibly minutes late. Being armed is the signal; it must not check for visible bars, because `setTimeoutAfter` (150s) may already have removed them. Notification IDs come from `NotificationManager.activeNotifications`, not memory.
- FCM handlers use `runBlocking` on FCM's worker thread on purpose (work must finish before the service is torn down).
- Cleartext HTTP and user CAs are allowed only in debug builds (`app/src/debug/res/xml/network_security_config.xml`); release is HTTPS + system CAs.
- Latency figures in `docs/metrics.md` were measured on 24 Oct 2026 (POCO M4 Pro, 4G). Phone clocks can be off by >0.5 s, so `HMD_LATENCY` needs `tools/clock_offsets.py` correction. Battery cost is still unmeasured. Don't put unmeasured numbers in docs.
- `sent_at` is stamped at dispatch in `push_throttler._prepare_dispatch` (not when the sample arrived), so throttle waits don't count as delivery latency.
- The extension samples ~100 ms after any state change even while its 2 s loop runs (`sampleSoon` in `poller.js`); without it a phone command's result waited for the next tick (measured 4.1 s → 1.8 s).

## Conventions

- Python: ruff (line length 100, rules E/F/I/UP/B/SIM), Pydantic v2 models in `schemas.py`, async everywhere, store/notifier behind ABCs. New tests go in `server/tests/` using fixtures in `conftest.py`.
- Extension: no bundler; keep zero dependencies. Logs are prefixed `[How's My Download]`.
- UI style on both clients is a dark "terminal" theme (purple `#8a05ff`, green `#61cf92`, monospace). Tokens are listed in `docs/design.md`. Notifications use the monochrome `R.drawable.ic_stat_hmd` small icon (generated from the pixel art), never the launcher icon.
- Never commit `google-services.json`, `service-account.json`, or `.env`. `commands.txt` (SSH/deploy notes) is local only.
