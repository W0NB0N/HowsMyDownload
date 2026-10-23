#!/usr/bin/env python3
"""Estimates the phone-vs-server clock offset, to correct HMD_LATENCY measurements.

HMD_LATENCY is (phone receipt time) - (server `sent_at`), taken on two different clocks. When
the clocks disagree by more than the delivery time, values go negative. This script measures
both offsets against this PC's clock, NTP-style: each probe is timestamped on both sides of
the request, the remote reading is compared with the midpoint, and the probes with the
shortest round trip (the least uncertainty) are kept.

    phone - PC   via `adb shell date +%s%N`
    server - PC  via the `timestamp` field of GET /health

Usage: python tools/clock_offsets.py https://your-server [--adb path/to/adb] [--probes 30]
Prints offset(phone - server) in ms; subtract it from each latency_ms
(tools/latency_report.py --offset-ms does this).
"""

import argparse
import statistics
import subprocess
import time
from datetime import datetime

import httpx


def best_offsets(probes: list[tuple[float, float]], keep: int = 5) -> tuple[float, float]:
    """probes: (round_trip_ms, offset_ms). Returns (median offset, worst RTT) of the tightest."""
    tight = sorted(probes)[:keep]
    return statistics.median(o for _, o in tight), tight[-1][0]


def phone_offset(adb: str, n: int) -> tuple[float, float]:
    probes = []
    for _ in range(n):
        t0 = time.time_ns()
        out = subprocess.run(
            [adb, "shell", "date", "+%s%N"], capture_output=True, text=True, check=True
        ).stdout.strip()
        t1 = time.time_ns()
        probes.append(((t1 - t0) / 1e6, (int(out) - (t0 + t1) / 2) / 1e6))
    return best_offsets(probes)


def server_offset(url: str, n: int) -> tuple[float, float]:
    probes = []
    with httpx.Client(timeout=10) as client:
        client.get(url)  # warm up the connection
        for _ in range(n):
            t0 = time.time_ns()
            body = client.get(url).json()
            t1 = time.time_ns()
            server_ns = datetime.fromisoformat(body["timestamp"]).timestamp() * 1e9
            probes.append(((t1 - t0) / 1e6, (server_ns - (t0 + t1) / 2) / 1e6))
    return best_offsets(probes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("server")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--probes", type=int, default=30)
    args = parser.parse_args()

    phone, phone_rtt = phone_offset(args.adb, args.probes)
    server, server_rtt = server_offset(args.server.rstrip("/") + "/health", args.probes)
    print(f"phone  - PC : {phone:+.0f} ms  (uncertainty <= {phone_rtt / 2:.0f} ms)")
    print(f"server - PC : {server:+.0f} ms  (uncertainty <= {server_rtt / 2:.0f} ms)")
    print(f"phone - server offset: {phone - server:+.0f} ms "
          f"(+/- {(phone_rtt + server_rtt) / 2:.0f} ms)")


if __name__ == "__main__":
    main()
