#!/usr/bin/env python3
"""Packaging script for DimSight Blender Extension.

Builds a clean, installable extension ZIP in the dist/ directory
suitable for Blender 4.2+ "Install from Disk" and GitHub Releases.
"""

import sys
import tomllib
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DIST_DIR = ROOT_DIR / "dist"

ADDON_FILES = [
    "blender_manifest.toml",
    "__init__.py",
    "geometry.py",
    "meshdata.py",
    "operators.py",
    "overlay.py",
    "props.py",
    "ui.py",
]


def main():
    manifest_path = ROOT_DIR / "blender_manifest.toml"
    if not manifest_path.exists():
        print(f"Error: manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)

    addon_id = manifest.get("id", "dimsight")
    version = manifest.get("version", "1.0.0")

    DIST_DIR.mkdir(exist_ok=True)
    versioned_zip = DIST_DIR / f"{addon_id}-{version}.zip"
    generic_zip = DIST_DIR / "DimSight.zip"

    for zip_path in (versioned_zip, generic_zip):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_name in ADDON_FILES:
                src = ROOT_DIR / rel_name
                if not src.exists():
                    print(f"Error: required file missing: {src}", file=sys.stderr)
                    sys.exit(1)
                zf.write(src, arcname=rel_name)
        print(f"Created {zip_path.name} ({zip_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
