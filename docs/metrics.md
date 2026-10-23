# Metrics, Benchmarks & Trade-offs

Every number on this page is either **measured** (tool, hardware and network named) or **by design** (it follows from the code, file named). Anything not measured yet is listed as such, with how to measure it.

---

## 1. End to end, as the user sees it (measured)

*Setup, 24 Oct 2026: production server on an Oracle Cloud VM (India region) running this repository. PC: Windows 11 laptop running Chrome with the extension, about 39 ms from the VM. Phone: POCO M4 Pro, Android 13, on 4G mobile data, connected over adb for measurement only.*

### Pause / resume from the phone

[`tools/measure_command_loop.py`](../tools/measure_command_loop.py) taps the button through adb, then polls the phone's notification text until the new state appears. Every timestamp comes from the PC clock, so no clock correction is involved. Polling resolution is one `dumpsys` call (~250 ms), which inflates each figure by ~125 ms on average.

| From tap until the phone shows… | Median | Range | n |
|---|---|---|---|
| "Pausing…" / "Resuming…" (local feedback) | **219 ms** | 181–255 ms | 10 |
| **PAUSED**, with another download running | **1.8 s** | 1.4–2.2 s | 5 |
| **running again**, with another download running | **1.7 s** | 1.6–2.0 s | 5 |
| **running again**, with nothing else transferring | **3.4 s** | 0.5–3.8 s | 5 |

The path is phone → server → (extension picks it up) → Chrome → server → FCM → phone.
- **Pickup while something is downloading:** commands ride back on the extension's 2 s sample responses, so pickup takes 0–2 s.
- **Pickup while nothing is transferring:** the extension polls for commands every 3 s, so pickup takes 0–3 s. That explains the wider range in the last row.

**What the measurement found.** The first run gave a median of **4.1 s** to PAUSED (3.6–4.4 s). After Chrome applied a command, the resulting state change waited for the extension's *next* 2 s tick, because "sample now" was ignored while the poll loop was already running. The poller now samples ~100 ms after any state change (debounced), which halved the round trip. The regression test is in `extension/test_commands.js` ("while already polling, a command's outcome is sampled at once").

### Server → phone push delivery

The app logs `HMD_LATENCY` for every accepted push: phone receipt time minus the server's `sent_at`. The two clocks disagreed by **−557 ms** (the phone was behind), measured at the start and the end of the run with [`tools/clock_offsets.py`](../tools/clock_offsets.py) (NTP-style, ±57 ms). Uncorrected, 307 of 386 values were negative, which makes raw readings meaningless on this phone.

| Corrected, 386 pushes over 15 min | Value |
|---|---|
| p50 | **448 ms** |
| p90 | **624 ms** |
| p95 | **680 ms** |
| p99 | **782 ms** |
| max | 2.2 s |

This covers server → Google FCM → phone over 4G, including the phone waking the app. When this run was taken, the server stamped `sent_at` when it built a push rather than when it dispatched it, so a push held back by the 2 s throttle counted its wait as latency (probably the 2.2 s max). That has since been fixed in `push_throttler.py`; the percentiles above are, if anything, slightly pessimistic.

### PC → server

[`tools/measure_rtt.py`](../tools/measure_rtt.py), `GET /health`:

| Connection | p50 | p95 |
|---|---|---|
| Reused (the extension while polling) | **39 ms** | 41 ms |
| Fresh (DNS + TCP + TLS) | 127 ms | 181 ms |

Derived, not measured directly: a Chrome progress change reaches the phone in about **0.5 s** at the median (~20 ms one way + ~2 ms server + 448 ms push), plus up to 2 s until the extension's next sample.

### Reproduce

```bash
python tools/measure_rtt.py https://your-server
python tools/clock_offsets.py https://your-server --adb adb      # prints the phone - server offset
adb logcat -c   # ... run a long download ...
adb logcat -d -s HMD_LATENCY > latency.log
python tools/latency_report.py latency.log --offset-ms <offset>
python tools/measure_command_loop.py "<file name>" --surface app --cycles 5   # app open, 2+ downloads
```

---

## 2. Server request handling (measured)

`python tools/bench_server.py`: an in-process ASGI benchmark covering auth, validation, tracking and throttling. No network and no FCM.

| Metric | Value |
|---|---|
| `POST /v1/samples` handling time, p50 | **1.5 ms** |
| `POST /v1/samples` handling time, p95 | **1.8–1.9 ms** |
| Sequential throughput, one worker | **~630 req/s** |
| FCM data payload, one active download | **~360 bytes** (FCM limit 4096; server budget 3584) |

*Environment: AMD Ryzen laptop (12 logical cores), Windows 11, Python 3.14, in-memory store, 50 pairings × 40 samples.*

One active download sends 0.5 samples/s, so a single worker has CPU headroom for roughly a thousand concurrent downloads. In practice Firestore and FCM round trips dominate. Auth reads are cached (`store/cached.py`), so Firestore sees about one read per pairing per 30 s rather than one per sample.

## 3. Push volume (by design)

| Rule | Where | Effect |
|---|---|---|
| Extension samples every 2 s while bytes move, and right after any state change; a paused download is reported once | `extension/background/poller.js` | ≤ ~1,800 samples/hour per PC |
| At most 1 progress push per 2 s per pairing; interim samples are merged | `server/throttler/push_throttler.py` | ≤ 1,800 progress pushes/hour per pairing |
| State changes (pause, complete, fail, add/remove) skip the throttle | same | Not delayed by the throttle window |
| While paused or recently failed, the extension polls for commands every 3 s for 10 min, then every 30 s | `poller.js` command watch | ≤ 200 requests in the first 10 min, then 2/min |

In the benchmark above, 2,000 samples sent back-to-back collapsed into 100 pushes (two per pairing).

## 4. Not yet measured

| Metric | How to measure |
|---|---|
| Phone battery cost per hour of mirrored download | `adb shell dumpsys batterystats --reset`, run a 1-hour download with the screen off, then `adb shell dumpsys batterystats com.notifs.app` (or Battery Historian). |
| Push latency on Wi-Fi and on other phones | As in §1, on another network or device. FCM delivery depends heavily on both. |
| Server memory / CPU on the VM under load | `docker stats notifs-api` during a load run. |

---

## 5. Architectural analysis: FCM vs LAN mode

Phase 9 (LAN / WebSocket mode) was evaluated and not built:

| Dimension | LAN mode (WebSocket) | FCM high-priority data |
|---|---|---|
| Background delivery on Android | Needs a foreground service with a permanent notification; `dataSync` foreground services are time-limited on Android 15+ | Google Play Services wakes the app briefly; no permanent notification |
| Doze | Sockets are suspended in deep Doze | High-priority messages get temporary Doze exemptions |
| Network topology | Fails on guest, campus and corporate networks that isolate clients | Works on any network, including cellular |
| PC side | Chrome extensions can't open listening sockets, so a native daemon would have to run on the PC | Only the extension; the server is hosted |
| TLS | Self-signed certificate plus pinning on the phone | Standard Let's Encrypt TLS, plus end-to-end filename encryption |
| Latency | Lower (single LAN hop) | Measured median 448 ms server → phone over 4G (§1), well under the 2 s update interval |
