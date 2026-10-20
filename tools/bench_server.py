"""In-process benchmark of the server's sample-handling cost (no network, no FCM).

Measures what the server itself adds: auth, validation, tracking, throttling. Network and
FCM delivery are measured end-to-end on a phone instead (tools/latency_report.py).

    python tools/bench_server.py [--pairings 50] [--samples 40]
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from server.main import create_app  # noqa: E402
from server.notifier.base import BaseNotifier  # noqa: E402
from server.notifier.fcm import build_data_payload  # noqa: E402
from server.rate_limiter import ALL_LIMITERS  # noqa: E402
from server.store.memory import InMemoryPairingStore  # noqa: E402
from server.throttler.push_throttler import PushThrottler  # noqa: E402
from server.tracker.manager import TrackerManager  # noqa: E402


class SizingNotifier(BaseNotifier):
    """Records the FCM data-map size each push would have, without sending anything."""

    def __init__(self) -> None:
        self.pushes = 0
        self.sizes: list[int] = []

    async def notify(self, payload, target_token=None) -> None:
        self.pushes += 1
        data = build_data_payload(payload)
        self.sizes.append(sum(len(k) + len(v.encode()) for k, v in data.items()))


async def run(pairings: int, samples: int) -> dict:
    app = create_app()
    notifier = SizingNotifier()
    app.state.pairing_store = InMemoryPairingStore()
    app.state.notifier = notifier
    app.state.tracker_manager = TrackerManager(notifier, throttler=PushThrottler(notifier))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
        creds = []
        for _ in range(pairings):
            for limiter in ALL_LIMITERS:  # benchmark the handler, not the per-IP limits
                limiter.reset()
            created = (await client.post("/v1/pairings", json={"pc_name": "Bench"})).json()
            await client.post(f"/v1/pairings/{created['code']}/claim", json={"fcm_token": "t"})
            creds.append(created)

        enc_name = "enc:v1:AAAAAAAAAAAAAAAA:" + "B" * 60  # ~ a 40-char filename, encrypted
        durations = []
        start = time.perf_counter()
        for i in range(samples):
            ALL_LIMITERS[0].reset()
            for c in creds:
                body = {
                    "pairing_id": c["pairing_id"],
                    "downloads": [{
                        "id": "1", "filename": enc_name, "bytes_downloaded": i * 1_000_000,
                        "total_bytes": samples * 1_000_000, "state": "downloading",
                    }],
                }
                t0 = time.perf_counter()
                resp = await client.post(
                    "/v1/samples", content=json.dumps(body),
                    headers={"Authorization": f"Bearer {c['secret']}",
                             "Content-Type": "application/json"},
                )
                durations.append((time.perf_counter() - t0) * 1000)
                assert resp.status_code == 200, resp.text
        elapsed = time.perf_counter() - start

    durations.sort()
    return {
        "requests": len(durations),
        "throughput_req_s": round(len(durations) / elapsed),
        "p50_ms": round(statistics.median(durations), 2),
        "p95_ms": round(durations[int(len(durations) * 0.95)], 2),
        "pushes_sent": notifier.pushes,
        "fcm_payload_bytes_1_download": statistics.median(notifier.sizes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairings", type=int, default=50)
    parser.add_argument("--samples", type=int, default=40)
    args = parser.parse_args()
    for key, value in asyncio.run(run(args.pairings, args.samples)).items():
        print(f"{key:>30}: {value}")


if __name__ == "__main__":
    main()
