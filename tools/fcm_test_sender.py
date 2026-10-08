"""Dev utility to send test FCM data notifications directly to an Android device.

Simulates real download lifecycles, stalls, failures, pauses, and multi-downloads.
"""

import argparse
import datetime
import json
import os
import sys
import time
import firebase_admin
from firebase_admin import credentials, messaging


def send_test_stream(
    cred_path: str,
    device_token: str,
    mode: str = "normal",
    filename: str = "ubuntu-24.04-desktop-amd64.iso",
    total_bytes: int = 6000000000,
    speed_bytes_sec: int = 25000000,
    steps: int = 15,
    interval_sec: float = 2.0,
) -> None:
    if not os.path.exists(cred_path):
        print(f"Error: Firebase credential file not found at '{cred_path}'", file=sys.stderr)
        sys.exit(1)

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

    print(f"Starting FCM test stream (mode: {mode.upper()}) to token: {device_token[:15]}...")

    step_bytes = total_bytes // steps
    current_bytes = 0
    seq = 1

    for i in range(1, steps + 1):
        if mode == "stall" and i > (steps // 2):
            # Stall mode: bytes stop advancing
            speed = 0
            eta = None
            state = "downloading"
        elif mode == "pause" and (steps // 3) <= i <= (2 * steps // 3):
            # Pause mode: paused state
            speed = 0
            eta = None
            state = "paused"
        elif mode == "fail" and i == (steps // 2 + 1):
            # Fail mode: download fails
            speed = 0
            eta = None
            state = "failed"
        else:
            current_bytes = min(current_bytes + step_bytes, total_bytes)
            pct = round((current_bytes / total_bytes) * 100, 1)
            speed = speed_bytes_sec
            eta = max(0, (total_bytes - current_bytes) // speed_bytes_sec)
            state = "completed" if current_bytes >= total_bytes else "downloading"

        pct = round((current_bytes / total_bytes) * 100, 1)

        downloads_list = [
            {
                "id": "test-dl-1",
                "filename": filename,
                "percentage": pct,
                "speed": speed,
                "eta_seconds": eta,
                "state": state,
                "bytes_downloaded": current_bytes,
                "total_bytes": total_bytes,
            }
        ]

        # Multi mode: add 2 extra concurrent downloads
        if mode == "multi":
            dl2_bytes = min(current_bytes // 2, 500000000)
            downloads_list.append({
                "id": "test-dl-2",
                "filename": "cuda_toolkit_installer.run",
                "percentage": round((dl2_bytes / 500000000) * 100, 1),
                "speed": speed // 2,
                "eta_seconds": max(0, (500000000 - dl2_bytes) // max(1, speed // 2)),
                "state": "downloading",
                "bytes_downloaded": dl2_bytes,
                "total_bytes": 500000000,
            })
            downloads_list.append({
                "id": "test-dl-3",
                "filename": "stream-recording.mkv",
                "percentage": None,
                "speed": 5000000,
                "eta_seconds": None,
                "state": "downloading",
                "bytes_downloaded": current_bytes // 3,
                "total_bytes": None,
            })

        payload = {
            "seq": str(seq),
            "sent_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": "chrome",
            "pc_name": "Desktop-PC",
            "downloads": json.dumps(downloads_list),
        }

        msg = messaging.Message(
            data=payload,
            token=device_token,
            android=messaging.AndroidConfig(priority="high", ttl=datetime.timedelta(seconds=30)),
        )

        try:
            response = messaging.send(msg)
            print(f"[{i}/{steps}] Seq #{seq} ({pct}%) -> {state.upper()} -> MsgId: {response}")
        except Exception as e:
            print(f"[{i}/{steps}] Error sending FCM push: {e}")

        seq += 1

        if state in ("completed", "failed") and mode != "multi":
            break

        time.sleep(interval_sec)

    print(f"FCM test stream ({mode}) finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FCM Test Sender")
    parser.add_argument("--token", required=True, help="Target Android device FCM token")
    parser.add_argument(
        "--cred",
        default="server/service-account.json",
        help="Path to Firebase service account JSON (default: server/service-account.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "stall", "pause", "fail", "multi"],
        default="normal",
        help="Simulation test mode (default: normal)",
    )
    parser.add_argument("--steps", type=int, default=15, help="Number of steps (default: 15)")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between pushes in sec (default: 2.0)")
    args = parser.parse_args()

    send_test_stream(
        cred_path=args.cred,
        device_token=args.token,
        mode=args.mode,
        steps=args.steps,
        interval_sec=args.interval,
    )
