#!/usr/bin/env python3
"""Packages the Chrome Extension into a clean production ZIP for Chrome Web Store submission.

Ships manifest.json plus everything under background/, popup/ and the PNG icons; tests and
the SVG icon source stay out. Exits non-zero if a file the manifest points at is missing.
"""

import json
import sys
import zipfile
from pathlib import Path

SHIPPED_DIRS = ("background", "popup")


def _manifest_references(manifest: dict) -> set[str]:
    """Files the manifest itself names (service worker, popup, icons)."""
    refs = {manifest["background"]["service_worker"], manifest["action"]["default_popup"]}
    refs.update(manifest.get("icons", {}).values())
    refs.update(manifest["action"].get("default_icon", {}).values())
    return refs


def collect_files(ext_dir: Path) -> list[str]:
    files = ["manifest.json"]
    for folder in SHIPPED_DIRS:
        files += sorted(
            p.relative_to(ext_dir).as_posix() for p in (ext_dir / folder).rglob("*") if p.is_file()
        )
    files += sorted(p.relative_to(ext_dir).as_posix() for p in (ext_dir / "icons").glob("*.png"))
    return files


def package_extension() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    ext_dir = repo_root / "extension"
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(exist_ok=True)

    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    files = collect_files(ext_dir)

    missing = sorted(_manifest_references(manifest) - set(files))
    if missing:
        sys.exit(f"[ERROR] manifest.json references files that would not be shipped: {missing}")

    zip_filename = dist_dir / f"hows-my-download-extension-v{manifest['version']}.zip"
    print(f"[PACKAGE] Packaging Chrome Extension v{manifest['version']} into {zip_filename.name}...")
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files:
            src_file = ext_dir / rel_path
            zf.write(src_file, arcname=rel_path)
            print(f"  + Added: {rel_path} ({src_file.stat().st_size:,} bytes)")

    print(f"\n[SUCCESS] Packaged successfully: {zip_filename} ({zip_filename.stat().st_size:,} bytes)")
    return zip_filename


if __name__ == "__main__":
    package_extension()
