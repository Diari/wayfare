#!/usr/bin/env python3
"""Build the ZIP to upload to the ChatGPT and Codex Plugins Directory:
the contents of plugins/wayfare at the ZIP root (plugin.json first).
Run: python3 tools/build_codex_zip.py [out-dir]"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "wayfare"


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = json.loads((PLUGIN / "plugin.json").read_text())["version"]
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", str(PLUGIN)],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    out = out_dir / f"wayfare-codex-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files, key=lambda x: (x != "plugins/wayfare/plugin.json", x)):
            src = ROOT / f
            if src.is_file():
                z.write(src, src.relative_to(PLUGIN).as_posix())
    print(f"{out} ({out.stat().st_size // 1024} KiB, {len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
