"""Summarize server -> phone push latency from Android logcat.

The app logs one line per accepted push:  I HMD_LATENCY: seq=42 latency_ms=187
(server `sent_at` to phone receipt; both clocks NTP-synced, so expect +-tens of ms of error).

Usage:
    adb logcat -c                      # clear, then run a real download for a while
    adb logcat -d -s HMD_LATENCY > latency.log
    python tools/latency_report.py latency.log
"""

import re
import statistics
import sys

LINE = re.compile(r"HMD_LATENCY.*?seq=(\d+)\s+latency_ms=(-?\d+)")


def percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        raise ValueError("no samples")
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo))


def summarize(lines) -> dict:
    values = sorted(int(m.group(2)) for line in lines if (m := LINE.search(line)))
    if not values:
        raise SystemExit("No HMD_LATENCY lines found. Is the phone paired and receiving pushes?")
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 50),
        "p90_ms": percentile(values, 90),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": values[-1],
        "mean_ms": round(statistics.fmean(values)),
        "negative": sum(v < 0 for v in values),  # >0 means clock skew dominates
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        report = summarize(f)
    for key, value in report.items():
        print(f"{key:>10}: {value}")


if __name__ == "__main__":
    main()
