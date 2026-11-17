"""Record docs/demo.gif from the live demo: one screenshot per scenario step.

    python tools/demo_gif.py [OUT.gif]      (default: docs/demo.gif)

Needs a Chromium-based browser (Edge, Chrome; TASKGRAPH_BROWSER picks one) and Pillow.
Run it by hand after the page or the scenario changes, and commit the GIF.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import demo_site  # noqa: E402
from tests.browser import run_headless  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("error: Pillow is needed: python -m pip install pillow")

SIZE = (1280, 760)
STEP_MS = 1900   # each step in the GIF
LAST_MS = 4000   # the last step


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else ROOT / "docs" / "demo.gif"
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        frames = demo_site.build(site)
        shots = []
        for n in range(1, len(frames) + 1):
            png = Path(tmp) / f"step{n:02}.png"
            uri = (site / "index.html").resolve().as_uri() + f"?lang=en&dir=lr&tab=graph&step={n}"
            run_headless(["--hide-scrollbars", "--window-size=%d,%d" % SIZE,
                          "--virtual-time-budget=1500", "--screenshot=" + str(png), uri])
            if not png.is_file():
                raise RuntimeError(f"no screenshot for step {n}")
            shots.append(Image.open(png).convert("RGB"))
        # one palette from all steps, so every state color keeps its own entry
        strip = Image.new("RGB", (SIZE[0], SIZE[1] * len(shots)))
        for k, shot in enumerate(shots):
            strip.paste(shot, (0, SIZE[1] * k))
        palette = strip.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        images = [s.quantize(palette=palette, dither=Image.Dither.NONE) for s in shots]
        durations = [STEP_MS] * (len(images) - 1) + [LAST_MS]
        out.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(out, save_all=True, append_images=images[1:], duration=durations,
                       loop=0, optimize=True)
    print(f"ok: {out} ({len(images)} frames, {out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
