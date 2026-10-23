"""Summarize server -> phone push latency from Android logcat.

The app logs one line per accepted push:  I HMD_LATENCY: seq=42 latency_ms=187
(server `sent_at` to phone receipt). The two clocks are rarely in sync to within the delivery
time (a phone 0.5 s behind is common), so measure their offset with tools/clock_offsets.py
and pass it as --offset-ms; raw values are only trustworthy if `negative` is 0.

Usage:
    adb logcat -c                      # clear, then run a real download for a while
    adb logcat -d -s HMD_LATENCY > latency.log
    python tools/clock_offsets.py https://your-server --adb adb   # -> phone - server offset
    python tools/latency_report.py latency.log --offset-ms -557
"""

import argparse
import re
import statistics

LINE = re.compile(r"HMD_LATENCY.*?seq=(\d+)\s+latency_ms=(-?\d+)")


def percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        raise ValueError("no samples")
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo))


def summarize(lines, offset_ms: int = 0) -> dict:
    """offset_ms: phone clock minus server clock; subtracted from every raw value."""
    values = sorted(int(m.group(2)) - offset_ms for line in lines if (m := LINE.search(line)))
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log")
    parser.add_argument("--offset-ms", type=int, default=0,
                        help="phone clock minus server clock, from tools/clock_offsets.py")
    args = parser.parse_args()
    with open(args.log, encoding="utf-8", errors="replace") as f:
        report = summarize(f, args.offset_ms)
    for key, value in report.items():
        print(f"{key:>10}: {value}")


if __name__ == "__main__":
    main()
