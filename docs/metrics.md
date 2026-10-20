# Metrics, Benchmarks & Trade-offs

Every number on this page is either **measured** (with the tool and hardware named) or **by design** (it follows from the code, with the file named). Numbers that haven't been measured yet are listed as such, together with how to measure them. Earlier revisions of this page gave latency, battery and memory figures that nothing in the repository produced; those have been removed.

---

## 1. Server request handling (measured)

`python tools/bench_server.py`: an in-process ASGI benchmark. It covers auth, validation, tracking and throttling, with no network and no FCM.

| Metric | Value |
|---|---|
| `POST /v1/samples` handling time, p50 | **1.5 ms** |
| `POST /v1/samples` handling time, p95 | **1.8–1.9 ms** |
| Sequential throughput, one worker | **~630 req/s** |
| FCM data payload, one active download | **~360 bytes** (FCM limit 4096; server budget 3584) |

*Environment: AMD Ryzen laptop (12 logical cores), Windows 11, Python 3.14, in-memory store, 50 pairings × 40 samples. Firestore and network round trips are excluded.*

For scale: one active download sends 0.5 samples/s, so a single worker has headroom for roughly a thousand concurrent downloads on server CPU alone. In practice Firestore and FCM calls dominate. Auth reads are cached (`store/cached.py`), so Firestore is hit about once per pairing per 30 s rather than on every sample.

## 2. Push volume (by design)

| Rule | Where | Effect |
|---|---|---|
| Extension samples every 2 s while bytes move; a paused download is reported once | `extension/background/poller.js` | ≤ 1,800 samples/hour per PC |
| At most 1 progress push per 2 s per pairing; interim samples are merged | `server/throttler/push_throttler.py` | ≤ 1,800 progress pushes/hour per pairing |
| State changes (pause, complete, fail, add/remove) skip the throttle | same | Immediate, not delayed by the throttle window |

The throttler mostly guards against bursts: several downloads changing state at once, retries after a reconnect, or a misbehaving client. A single steady download already arrives at the throttle rate, so the throttler removes little in that case. In the benchmark above, 2,000 samples sent back-to-back collapsed into 100 pushes (two per pairing).

## 3. Not yet measured

| Metric | How to measure |
|---|---|
| Server → phone delivery latency (p50/p95/p99) | The app logs `HMD_LATENCY seq=… latency_ms=…` for every accepted push (`NotifFcmService.logDeliveryLatency`). Run `adb logcat -c`, do a long download, run `adb logcat -d -s HMD_LATENCY > latency.log`, then `python tools/latency_report.py latency.log`. Both clocks use NTP, so expect ± tens of ms of error. |
| Phone battery cost per hour of mirrored download | Reset `adb shell dumpsys batterystats --reset`, run a 1-hour download with the screen off, then use `adb shell dumpsys batterystats com.notifs.app` (or Battery Historian). |
| Server memory / CPU on the Oracle VM | `docker stats notifs-api` during a load run. |

---

## 4. Architectural analysis: FCM vs LAN mode

Phase 9 (LAN / WebSocket mode) was evaluated and not built:

| Dimension | LAN mode (WebSocket) | FCM high-priority data |
|---|---|---|
| Background delivery on Android | Needs a foreground service with a permanent notification; `dataSync` foreground services are time-limited on Android 15+ | Google Play Services wakes the app briefly; no permanent notification |
| Doze | Sockets are suspended in deep Doze | High-priority messages get temporary Doze exemptions |
| Network topology | Fails on guest, campus and corporate networks that isolate clients | Works on any network, including cellular |
| PC side | Chrome extensions can't open listening sockets, so a native daemon would have to run on the PC | Only the extension; the server is hosted |
| TLS | Self-signed certificate plus pinning on the phone | Standard Let's Encrypt TLS, plus end-to-end filename encryption |
| Latency | Lower (single LAN hop) | Higher (FCM relay), but below what matters for progress updates every 2 s |
