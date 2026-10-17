"""Render showreel.html to frames, then to MP4 / GIF / WebP.

    python3 build.py <font-dir>          # inline fonts -> showreel.html
    python3 render.py <frames-dir> [fps] [--lite]   # needs playwright (chromium)

--lite freezes the drifting background so a GIF compresses well.
Then encode with ffmpeg (see README in this folder).
"""
import pathlib, subprocess, sys
from concurrent.futures import ProcessPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
DUR = 60.0
LITE = "--lite" in sys.argv

def work(args):
    frames, fps, lo, hi = args
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(f"file://{HERE/'showreel.html'}?render" + ("&lite" if LITE else ""))
        pg.wait_for_function("window.READY===true", timeout=20000)
        for i in range(lo, hi):
            if pathlib.Path(f"{frames}/f{i:05d}.png").exists():
                continue
            pg.evaluate(f"seek({i / fps})")
            pg.screenshot(path=f"{frames}/f{i:05d}.png")
        b.close()
    return hi - lo

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    frames = pathlib.Path(args[0]); frames.mkdir(parents=True, exist_ok=True)
    fps = int(args[1]) if len(args) > 1 else 60
    n = int(DUR * fps); W = 2
    chunks = [(str(frames), fps, k * n // W, (k + 1) * n // W) for k in range(W)]
    with ProcessPoolExecutor(W) as ex:
        print("frames:", sum(ex.map(work, chunks)))
