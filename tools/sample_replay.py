"""Dev utility to replay recorded download sample traces to the local or remote server.

The server always requires a pairing's bearer secret. Without --token this creates a fresh
(unclaimed) pairing and replays with its secret, so the samples show up on the console
notifier. An unclaimed pairing stops authenticating once its 5-minute pairing code expires,
which bounds how long such a replay can run (100 samples at 2 s is about 3.5 minutes).

Usage:
    python tools/sample_replay.py tools/sample_traces/ubuntu_download_trace.json
    python tools/sample_replay.py trace.json --url https://your-server --token <extension secret>
"""

import argparse
import json
import sys
import time

import httpx


def create_pairing(client: httpx.Client) -> str:
    resp = client.post("/v1/pairings", json={"pc_name": "Replay-PC"})
    resp.raise_for_status()
    print(f"Created unclaimed pairing {resp.json()['pairing_id']} for this replay")
    return resp.json()["secret"]


def replay(
    file_path: str, server_url: str, token: str | None = None, interval: float = 2.0
) -> None:
    try:
        with open(file_path, encoding="utf-8") as f:
            samples = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client(base_url=server_url, timeout=5.0)
    secret = token or create_pairing(client)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}

    print(f"Replaying {len(samples)} samples to {server_url}/v1/samples ...")
    for i, sample in enumerate(samples):
        try:
            resp = client.post("/v1/samples", json=sample, headers=headers)
            print(f"[{i + 1}/{len(samples)}] Status: {resp.status_code} - {resp.text}")
        except httpx.HTTPError as e:
            print(f"[{i + 1}/{len(samples)}] Failed: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay download samples.")
    parser.add_argument("file", help="Path to samples JSON file")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend server URL")
    parser.add_argument("--token", default=None,
                        help="Extension bearer secret; omit to create a throwaway pairing")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between samples")
    args = parser.parse_args()
    replay(args.file, args.url, args.token, args.interval)
