#!/usr/bin/env python3
"""Times the pause/resume round trip as the user sees it, on a phone connected over adb.

For each cycle it taps the notification's Pause button, then Resume, and polls the phone's
notification text until it changes. All times are taken on this PC's clock, so no clock
offsets are involved. Measured:

    tap -> "Pausing…"   local feedback (the app's own UI update)
    tap -> "PAUSED"     phone -> server -> extension -> browser -> server -> FCM -> phone
    tap -> speed shown  same loop for resume

Resolution is one `dumpsys notification` call (~250 ms); a tap costs one `adb shell input`
call (~100 ms) and is timestamped at its midpoint.

Requirements: a download running in the browser and the phone paired; for --surface notification
an open notification shade (the tool expands the notification), for --surface app the app
open on screen showing the download.

Usage: python tools/measure_command_loop.py "<download title>" [--cycles 3] [--adb path]
"""

import argparse
import re
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET

TITLE_RE = re.compile(r"android\.title=String \((.*)\)")
TEXT_RE = re.compile(r"android\.text=String \((.*)\)")
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
TIMEOUT_S = 30


def adb(args: list[str], adb_path: str) -> str:
    return subprocess.run(
        [adb_path, *args], capture_output=True, encoding="utf-8", errors="replace", check=True
    ).stdout


def notification_text(title: str, adb_path: str) -> str | None:
    dump = adb(["shell", "dumpsys", "notification", "--noredact"], adb_path)
    for record in dump.split("NotificationRecord(")[1:]:
        found_title = TITLE_RE.search(record)
        found_text = TEXT_RE.search(record)
        if found_title and found_text and found_title.group(1) == title:
            return found_text.group(1)
    return None


def _centre(node: ET.Element) -> tuple[int, int]:
    x1, y1, x2, y2 = map(int, BOUNDS_RE.match(node.get("bounds")).groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def _find_in_notification(title: str, matches, adb_path: str) -> tuple[int, int] | None:
    """Centre of the first node satisfying `matches` in the notification titled `title`."""
    adb(["shell", "uiautomator", "dump", "/sdcard/hmd_ui.xml"], adb_path)
    root = ET.fromstring(adb(["shell", "cat", "/sdcard/hmd_ui.xml"], adb_path))
    parent = {child: node for node in root.iter() for child in node}
    for node in root.iter("node"):
        if node.get("text") != title:
            continue
        ancestor = node
        # Widen to the smallest container that holds a match; stop at the notification row
        while ancestor in parent:
            ancestor = parent[ancestor]
            found = next((c for c in ancestor.iter("node") if matches(c)), None)
            if found is not None:
                return _centre(found)
            if ancestor.get("resource-id") == "com.android.systemui:id/expanded":
                break
    return None


def find_button(title: str, label: str, adb_path: str) -> tuple[int, int]:
    """Centre of the `label` button in the notification titled `title`, expanding it if needed."""
    is_button = lambda n: n.get("text", "").lower() == label.lower()  # noqa: E731
    # Re-posting a notification can collapse it again, so allow a few expand attempts
    for _ in range(4):
        if (centre := _find_in_notification(title, is_button, adb_path)) is not None:
            return centre
        expand = _find_in_notification(title, lambda n: n.get("content-desc") == "Expand", adb_path)
        if expand is not None:
            adb(["shell", "input", "tap", str(expand[0]), str(expand[1])], adb_path)
        time.sleep(1.0)
    raise SystemExit(f"No '{label}' button found for '{title}'. Is the notification shade open?")


def tap_and_wait(title: str, label: str, done, adb_path: str) -> dict[str, float]:
    x, y = find_button(title, label, adb_path)
    t_before = time.monotonic()
    adb(["shell", "input", "tap", str(x), str(y)], adb_path)
    t_tap = (t_before + time.monotonic()) / 2
    marks: dict[str, float] = {}
    while time.monotonic() - t_tap < TIMEOUT_S:
        text = notification_text(title, adb_path) or ""
        elapsed = (time.monotonic() - t_tap) * 1000
        if "…" in text and "pending" not in marks:
            marks["pending"] = elapsed
        if done(text):
            marks["done"] = elapsed
            return marks
    raise SystemExit(f"Timed out waiting after tapping {label}; last text: {text!r}")


def summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (f"median {statistics.median(values):.0f} ms  "
            f"(min {min(values):.0f}, max {max(values):.0f}, n={len(values)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title", help="notification title, i.e. the file name")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--adb", default="adb")
    parser.add_argument(
        "--surface", choices=["notification", "app"], default="notification",
        help="tap the notification buttons, or the buttons in the open app",
    )
    args = parser.parse_args()
    labels = {"Pause": "Pause", "Resume": "Resume"} if args.surface == "notification" else {
        "Pause": "> pause", "Resume": "> resume"}

    def is_paused(text: str) -> bool:
        return "PAUSED" in text

    def is_running(text: str) -> bool:
        return "/s" in text and "…" not in text

    pending, paused, resumed = [], [], []
    current = notification_text(args.title, args.adb)
    if current is None:
        raise SystemExit(f"No notification titled '{args.title}'")
    # Start from whatever state the download is in, then alternate
    actions = ["Resume", "Pause"] if is_paused(current) else ["Pause", "Resume"]
    for cycle in range(1, args.cycles + 1):
        for label in actions:
            done = is_paused if label == "Pause" else is_running
            marks = tap_and_wait(args.title, labels[label], done, args.adb)
            print(f"cycle {cycle}: {label.lower():<6} -> state shown after {marks['done']:.0f} ms"
                  + (f" ('…' after {marks['pending']:.0f} ms)" if "pending" in marks else ""))
            (paused if label == "Pause" else resumed).append(marks["done"])
            if "pending" in marks:
                pending.append(marks["pending"])
            time.sleep(3)

    print(f"tap -> 'Pausing…' : {summary(pending)}")
    print(f"tap -> PAUSED     : {summary(paused)}")
    print(f"tap -> resumed    : {summary(resumed)}")


if __name__ == "__main__":
    main()
