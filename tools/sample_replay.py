"""Dev utility to replay recorded download sample traces to the local or remote server."""

import argparse
import json
import sys
import time

import httpx


def replay(file_path: str, server_url: str, token: str | None = None) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            samples = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    client = httpx.Client(base_url=server_url, timeout=5.0)

    print(f"Replaying {len(samples)} samples to {server_url}/v1/samples ...")
    for i, sample in enumerate(samples):
        try:
            resp = client.post("/v1/samples", json=sample, headers=headers)
            print(f"[{i+1}/{len(samples)}] Status: {resp.status_code} - {resp.text}")
        except httpx.HTTPError as e:
            print(f"[{i+1}/{len(samples)}] Failed: {e}")
        time.sleep(2.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay download samples.")
    parser.add_argument("file", help="Path to samples JSON file")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend server URL")
    parser.add_argument("--token", default=None, help="Bearer pairing token")
    args = parser.parse_args()
    replay(args.file, args.url, args.token)
