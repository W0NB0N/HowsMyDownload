#!/usr/bin/env python3
"""Packages the Chrome Extension into a clean production ZIP for Chrome Web Store submission."""

import json
import zipfile
from pathlib import Path


def package_extension():
    repo_root = Path(__file__).resolve().parent.parent
    ext_dir = repo_root / "extension"
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(exist_ok=True)

    manifest_path = ext_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    version = manifest.get("version", "0.1.0")
    zip_filename = dist_dir / f"hows-my-download-extension-v{version}.zip"

    # Files and folders to include
    include_paths = [
        "manifest.json",
        "background/api.js",
        "background/commands.js",
        "background/crypto.js",
        "background/poller.js",
        "background/service-worker.js",
        "icons/icon16.png",
        "icons/icon48.png",
        "icons/icon128.png",
        "icons/pair-icon.png",
        "popup/popup.html",
        "popup/popup.css",
        "popup/popup.js",
        "popup/qrcode.js",
        "popup/pair-icon.png",
    ]

    print(f"[PACKAGE] Packaging Chrome Extension v{version} into {zip_filename.name}...")
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in include_paths:
            src_file = ext_dir / rel_path
            if src_file.exists():
                zf.write(src_file, arcname=rel_path)
                print(f"  + Added: {rel_path} ({src_file.stat().st_size:,} bytes)")
            else:
                print(f"  ! Warning: missing {rel_path}")

    total_size = zip_filename.stat().st_size
    print(f"\n[SUCCESS] Packaged successfully: {zip_filename} ({total_size:,} bytes)")
    return zip_filename


if __name__ == "__main__":
    package_extension()
