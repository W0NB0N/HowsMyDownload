#!/usr/bin/env python3
"""Checks a google-services.json before an APK is built from it.

An APK built from the wrong file installs fine but never receives a push, which is hard to
diagnose on a phone. Fail the build instead when the file:
  - is not valid JSON or not a google-services.json,
  - is the placeholder shipped in this repo (google-services.json.example), or
  - has no Android client for the package name being built.

Usage: python tools/check_google_services.py <google-services.json> <application id>
"""

import json
import sys

PLACEHOLDER_PROJECT_ID = "hows-my-download-mock"


def check(path: str, application_id: str) -> str:
    """Returns the Firebase project ID, or raises ValueError explaining what is wrong."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"cannot read {path} as JSON: {err}") from err

    project_id = data.get("project_info", {}).get("project_id")
    if not project_id or "client" not in data:
        raise ValueError(f"{path} is not a google-services.json (no project_info/client)")
    if project_id == PLACEHOLDER_PROJECT_ID:
        raise ValueError(
            "this is the placeholder google-services.json.example; download the real file "
            "from your Firebase project settings"
        )

    packages = sorted(
        client.get("client_info", {}).get("android_client_info", {}).get("package_name", "")
        for client in data["client"]
    )
    if application_id not in packages:
        raise ValueError(
            f"no Android app '{application_id}' in Firebase project '{project_id}' "
            f"(it has: {', '.join(p for p in packages if p) or 'none'}). Register that package "
            "name in Firebase, or build with the matching application ID."
        )
    return project_id


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        project_id = check(sys.argv[1], sys.argv[2])
    except ValueError as err:
        sys.exit(f"google-services.json check failed: {err}")
    print(f"google-services.json OK: project '{project_id}', package '{sys.argv[2]}'")


if __name__ == "__main__":
    main()
