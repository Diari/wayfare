#!/usr/bin/env python3
"""Pre-check the Claude plugin against the directory's automated checks
(claude.com/docs/plugins/pre-submission-checklist). The portal's Validate is
the authority; this catches the common problems before you push."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "wayfare-claude"
IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".woff", ".woff2", ".ttf", ".otf"}
TEXT = {".md", ".json", ".py", ".html", ".txt", ".js", ".mjs", ".sql", ".svg", ".toml", ".yaml", ".yml", ".sh", ""}
SYSTEM = {".DS_Store", "Thumbs.db", "desktop.ini"}
BAD_NAME = re.compile(r'[:<>"|?*]|[. ]$')


def main() -> int:
    errs, warns = [], []
    # What GitHub (and so the directory) sees: the files Git tracks, plus new files not ignored.
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", str(PLUGIN)],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    files = [ROOT / f for f in out if (ROOT / f).is_file()]
    if len(files) > 512:
        warns.append(f"{len(files)} files (over 512 is held for a reviewer)")
    for f in files:
        rel = f.relative_to(PLUGIN)
        if f.name in SYSTEM or "__MACOSX" in rel.parts:
            errs.append(f"{rel}: system file")
        if any(BAD_NAME.search(p) for p in rel.parts):
            errs.append(f"{rel}: name not valid on Windows or macOS")
        size = f.stat().st_size
        if size > 5 * 1024 * 1024:
            errs.append(f"{rel}: over 5 MiB")
        if f.suffix.lower() not in IMAGE and size > 256 * 1024:
            warns.append(f"{rel}: over 256 KiB (held for a reviewer)")
        if f.suffix.lower() not in IMAGE | TEXT:
            warns.append(f"{rel}: binary type {f.suffix} (held for a reviewer)")
        if f.is_symlink():
            errs.append(f"{rel}: symbolic link")
    lower = {}
    for f in files:
        k = str(f.relative_to(PLUGIN)).lower()
        if k in lower:
            errs.append(f"{f.relative_to(PLUGIN)}: differs only by case from {lower[k]}")
        lower[k] = f.relative_to(PLUGIN)
    readme = PLUGIN / "README.md"
    if not readme.exists():
        errs.append("README.md missing")
    else:
        text = re.sub(r"```.*?```", "", readme.read_text(encoding="utf-8"), flags=re.S)
        if len(re.findall(r"\b\w+\b", text)) < 40:
            errs.append("README.md under 40 words outside code blocks")
    m = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    if not (PLUGIN / "LICENSE").exists() and not m.get("license"):
        errs.append("no LICENSE file and no license field")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", m["name"]):
        errs.append("name must be lowercase letters, digits and hyphens")
    for k in ("description", "author", "version"):
        if not m.get(k):
            warns.append(f"plugin.json: {k} missing")
    for k in ("icon",):
        if m.get(k) and not (PLUGIN / m[k][2:]).exists():
            errs.append(f"plugin.json: {k} {m[k]} does not exist")
    for k in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl", "homepage"):
        if m.get(k) and not m[k].startswith("https://"):
            errs.append(f"plugin.json: {k} must be https://")
    if (PLUGIN / "bin").exists():
        errs.append("bin/ prevents install on claude.ai and Cowork")
    for w in warns:
        print("warning:", w)
    for e in errs:
        print("BLOCKING:", e)
    print(f"{len(files)} files checked: " + ("OK" if not errs else f"{len(errs)} blocking"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
