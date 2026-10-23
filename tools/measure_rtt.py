#!/usr/bin/env python3
"""Measures the PC -> server leg: round-trip time of GET /health from this machine.

Every sample (extension -> server) and every command pickup crosses this leg. Reports a
reused connection (what the extension sees while polling) and fresh connections (DNS + TCP +
TLS, what the first request after idle sees).

Usage: python tools/measure_rtt.py https://your-server [--requests 100]
"""

import argparse
import statistics
import time

import httpx


def percentiles(values: list[float]) -> str:
    ordered = sorted(values)

    def pct(p: float) -> float:
        k = (len(ordered) - 1) * p / 100
        lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)

    return (
        f"n={len(values)}  p50={pct(50):.0f} ms  p90={pct(90):.0f} ms  p95={pct(95):.0f} ms  "
        f"min={ordered[0]:.0f} ms  max={ordered[-1]:.0f} ms  mean={statistics.fmean(values):.0f} ms"
    )


def timed_get(client: httpx.Client, url: str) -> float:
    start = time.perf_counter()
    client.get(url).raise_for_status()
    return (time.perf_counter() - start) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("server")
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()
    url = args.server.rstrip("/") + "/health"

    with httpx.Client(timeout=10) as client:
        timed_get(client, url)  # warm up DNS and the connection
        warm = [timed_get(client, url) for _ in range(args.requests)]

    fresh = []
    for _ in range(max(10, args.requests // 5)):
        with httpx.Client(timeout=10) as client:
            fresh.append(timed_get(client, url))

    print(f"Reused connection : {percentiles(warm)}")
    print(f"Fresh connection  : {percentiles(fresh)}")


if __name__ == "__main__":
    main()
