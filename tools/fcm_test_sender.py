"""Dev utility to send test FCM data notifications directly to an Android device."""

import argparse
import datetime
import json
import time
import firebase_admin
from firebase_admin import credentials, messaging


def send_test_stream(
    cred_path: str,
    device_token: str,
    filename: str = "ubuntu-24.04-desktop-amd64.iso",
    total_bytes: int = 6000000000,
    speed_bytes_sec: int = 25000000,
    steps: int = 20,
) -> None:
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

    download_id = "test-dl-1"
    step_bytes = total_bytes // steps
    current_bytes = 0

    print(f"Sending {steps} simulated progress updates to device...")

    for i in range(1, steps + 1):
        current_bytes = min(current_bytes + step_bytes, total_bytes)
        pct = round((current_bytes / total_bytes) * 100, 1)
        eta = max(0, (total_bytes - current_bytes) // speed_bytes_sec)
        state = "completed" if current_bytes >= total_bytes else "downloading"

        item = {
            "id": download_id,
            "filename": filename,
            "percentage": pct,
            "speed": speed_bytes_sec,
            "eta_seconds": eta,
            "state": state,
            "bytes_downloaded": current_bytes,
            "total_bytes": total_bytes,
        }

        payload = {
            "seq": str(i),
            "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "chrome",
            "pc_name": "Desktop-PC",
            "downloads": json.dumps([item]),
        }

        msg = messaging.Message(
            data=payload,
            token=device_token,
            android=messaging.AndroidConfig(priority="high", ttl=datetime.timedelta(seconds=30)),
        )

        try:
            response = messaging.send(msg)
            print(f"[{i}/{steps}] Sent seq={i} ({pct}%) -> message_id: {response}")
        except Exception as e:
            print(f"[{i}/{steps}] Error sending message: {e}")

        if state == "completed":
            break

        time.sleep(2.0)

    print("Test stream finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FCM Test Sender")
    parser.add_argument("--cred", required=True, help="Path to Firebase service account JSON")
    parser.add_argument("--token", required=True, help="Target Android FCM token")
    args = parser.parse_args()
    send_test_stream(args.cred, args.token)
