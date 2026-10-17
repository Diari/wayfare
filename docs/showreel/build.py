"""Inline the fonts into showreel.src.html -> showreel.html (self-contained)."""
import base64, pathlib, sys
here = pathlib.Path(__file__).parent
fontdir = pathlib.Path(sys.argv[1])
css = []
for w in (500, 600, 700, 800, 900):
    b = base64.b64encode((fontdir / f"figtree-latin-{w}-normal.woff2").read_bytes()).decode()
    css.append(f'@font-face{{font-family:"Figtree";font-weight:{w};src:url(data:font/woff2;base64,{b}) format("woff2")}}')
b = base64.b64encode((fontdir / "jetbrains-mono-latin-500-normal.woff2").read_bytes()).decode()
css.append(f'@font-face{{font-family:"JetBrains Mono";font-weight:400 600;src:url(data:font/woff2;base64,{b}) format("woff2")}}')
src = (here / "showreel.src.html").read_text()
(here / "showreel.html").write_text(src.replace("/*FONTS*/", "\n".join(css)))
print("ok")
