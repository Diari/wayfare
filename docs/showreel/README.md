# Wayfare showreel

The 30-second showreel in `docs/media/` is rendered from `showreel.html`, a
self-contained animation in the trip page's own colors and type (Figtree).
Every frame is a pure function of time, so the render is exact.

Open `showreel.html` in a browser to watch it loop live.

## Render

```bash
# 1. Inline the fonts (woff2 files from @fontsource/figtree and
#    @fontsource/jetbrains-mono) into showreel.html
python3 build.py <font-dir>

# 2. Frames (Playwright + Chromium)
python3 render.py /tmp/frames 60          # full quality, for the MP4
python3 render.py /tmp/lite 15 --lite     # static background, for the GIF

# 3. Encode
ffmpeg -framerate 60 -i /tmp/frames/f%05d.png -c:v libx264 -preset slow -crf 18 \
  -pix_fmt yuv420p -tune animation -movflags +faststart ../media/wayfare-showreel.mp4
ffmpeg -framerate 15 -i /tmp/lite/f%05d.png -vf "scale=960:-1:flags=lanczos,split[a][b];\
[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  ../media/wayfare-showreel.gif
```

Edit `showreel.src.html`, not `showreel.html`. Scene timings live in
`build()`: each `at(element, time, {props}, easing)` call is one keyframe.
The trip data is the invented sample trip from `samples/`.
