#!/usr/bin/env python3
"""Copy the shared engine, scripts, pages and samples from the Claude plugin
(plugins/wayfare-claude) into the Codex plugin (plugins/wayfare).

The Codex plugin (plugins/wayfare) must be self-contained, because Codex
installs a plugin folder on its own. Run this after changing any shared file;
tests/test_engine.py fails when the copies drift.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "plugins" / "wayfare-claude"   # the Claude plugin holds the shared originals
PLUGIN = ROOT / "plugins" / "wayfare"
SHARED = {
    "scripts/wayfare.py": "scripts/wayfare.py",
    "scripts/weather.py": "scripts/weather.py",
    "scripts/flight_status.py": "scripts/flight_status.py",
    "scripts/fare_check.py": "scripts/fare_check.py",
    "scripts/stay_check.py": "scripts/stay_check.py",
    "scripts/planner.py": "scripts/planner.py",
    "dashboard/plan.html": "pages/plan.html",
    "samples/plans.sample.json": "samples/plans.sample.json",
    "dashboard/trip.html": "pages/trip.html",
    "dashboard/home.html": "pages/home.html",
    "reference/data-model.md": "reference/data-model.md",
    "samples/bookings.sample.json": "samples/bookings.sample.json",
    "samples/profile.sample.json": "samples/profile.sample.json",
    "samples/fares.sample.json": "samples/fares.sample.json",
    "samples/guide.lisbon-2026-11.sample.json": "samples/guide.lisbon-2026-11.sample.json",
    "samples/guide.berlin-2026-12.sample.json": "samples/guide.berlin-2026-12.sample.json",
    "LICENSE": "LICENSE",
}


def drift() -> list[str]:
    out = []
    for src, dst in SHARED.items():
        a, b = SOURCE / src, PLUGIN / dst
        if not b.exists() or a.read_bytes() != b.read_bytes():
            out.append(dst)
    return out


def main() -> int:
    if "--check" in sys.argv:
        d = drift()
        print("in sync" if not d else "out of sync: " + ", ".join(d))
        return 1 if d else 0
    for src, dst in SHARED.items():
        b = PLUGIN / dst
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / src, b)
    print(f"copied {len(SHARED)} files into {PLUGIN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
