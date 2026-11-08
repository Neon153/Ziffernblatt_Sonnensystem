"""
Pre-renders every bitmap of the watch face into watchface/src/main/res/drawable-nodpi,
using the look of the approved reference image (tools/look.py).

  hintergrund.png      static layer at 2x (900 px): stars, nebula, orbit lines, asteroid belt,
                       sun with corona / glow / bloom / light rings, bezel ticks, battery track
  komet.png            opaque crop of the same layer with the comet (shown if enabled)
  sonne_overlay.png    crop around the sun with soft alpha, drawn over planets passing behind it
  <planet>_00..23.png  each planet lit by the sun for 24 orbital positions (baked lighting:
                       terminator, crescents in front of the sun, city lights, ring shadow)
  mond_00..23, mond_io/europa/ganymed/kallisto, mondphase_0..7

    pip install numpy scipy pillow
    python tools/render_assets.py
"""
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from config import *  # noqa
import look

OUT = os.path.join(os.path.dirname(__file__), "..", "watchface", "src", "main", "res", "drawable-nodpi")
os.makedirs(OUT, exist_ok=True)
Fs = look.F          # 2: files are rendered at 2x the canvas size


def save(arr, name, mode="RGBA"):
    Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), mode).save(os.path.join(OUT, name + ".png"),
                                                                                  optimize=True)


def render_planets():
    for p in PLANETS:
        n = sprite_size(p) * Fs
        vig = look.vignette_at(p["r"] * Fs * 0.85)
        for k in range(N_FRAMES):
            spr = look.planet_sprite(int(n), p["R"] * Fs, p["key"], light_dir(k * 360 / N_FRAMES), vignette=vig)
            save(spr, f"{p['key']}_{k:02d}")
    n = small_sprite(MOON["R"]) * Fs
    for k in range(N_FRAMES):
        save(look.planet_sprite(int(n), MOON["R"] * Fs, "mond", light_dir(k * 360 / N_FRAMES)), f"mond_{k:02d}")
    for g in GALILEAN:
        n = small_sprite(g["R"]) * Fs
        save(look.planet_sprite(int(n), g["R"] * Fs, g["key"], (0.0, -0.3, 0.95)), f"mond_{g['key']}")


def comet_ref():
    return COMET_HEAD[0] * Fs, COMET_HEAD[1] * Fs


def render_static():
    orbits_ref = [p["r"] * Fs for p in PLANETS]
    bg = look.render_background(orbits_ref)
    save(bg, "hintergrund", "RGB")
    # comet: opaque crop of the background rendered with the comet
    with_c = look.render_background(orbits_ref, comet=comet_ref())
    diff = np.abs(with_c - bg).max(-1) > 1.5 / 255
    ys, xs = np.nonzero(diff)
    x0, x1 = (xs.min() // 2) * 2 - 2, (xs.max() // 2) * 2 + 4
    y0, y1 = (ys.min() // 2) * 2 - 2, (ys.max() // 2) * 2 + 4
    save(with_c[y0:y1, x0:x1], "komet", "RGB")
    # sun overlay: crop of the background around the sun, alpha 1 inside, soft edge outside
    n = int(SUN_OVERLAY * Fs)
    cx, cy = int(SUN_X * Fs), int(SUN_Y * Fs)
    crop = bg[cy - n // 2:cy + n // 2, cx - n // 2:cx + n // 2]
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.hypot(xx - n / 2 + 0.5, yy - n / 2 + 0.5)
    rs = SUN_R * Fs
    a = np.clip((rs + 10 - d) / 9, 0, 1) ** 1.5    # opaque over the sun disc, gone 10 ref px outside
    save(np.dstack([crop, a]), "sonne_overlay")
    return (x0 / Fs, y0 / Fs, (x1 - x0) / Fs, (y1 - y0) / Fs)


def render_moonphases():
    """8 icons for [MOON_PHASE_TYPE] 0..7: new, waxing crescent, first quarter, waxing gibbous,
    full, waning gibbous, last quarter, waning crescent (northern hemisphere)"""
    D, ss = int(MOONPHASE_ICON * Fs * 4), 4
    yy, xx = np.mgrid[0:D, 0:D].astype(np.float32)
    c = (D - 1) / 2
    R = D / 2 - 2 * ss
    X, Y = xx - c, yy - c
    z = np.sqrt(np.clip(R * R - X * X - Y * Y, 0, None))
    N = np.stack([X, Y, z], -1) / R
    disc = np.clip(R - np.hypot(X, Y) + 0.5 * ss, 0, ss) / ss
    for k in range(8):
        ph = k / 8 * 2 * np.pi
        Lv = np.array([np.sin(ph), 0.0, -np.cos(ph)])
        lit = np.clip((N @ Lv) * 4, 0, 1)
        col = np.array([0.88, 0.84, 0.75]) * lit[..., None] + np.array([0.157, 0.149, 0.133]) * (1 - lit)[..., None]
        prem = col * disc[..., None]
        n = D // ss
        prem = prem.reshape(n, ss, n, ss, 3).mean(axis=(1, 3))
        a = disc.reshape(n, ss, n, ss).mean(axis=(1, 3))
        rgb = np.where(a[..., None] > 1e-4, prem / np.maximum(a[..., None], 1e-4), 0)
        save(np.dstack([rgb, a]), f"mondphase_{k}")


if __name__ == "__main__":
    for f in os.listdir(OUT):
        if f != "preview.png":
            os.remove(os.path.join(OUT, f))
    render_planets()
    box = render_static()
    render_moonphases()
    with open(os.path.join(os.path.dirname(__file__), "komet_box.txt"), "w") as fh:
        fh.write(" ".join(f"{v:g}" for v in box))
    print("comet box (canvas px):", box)
    print("done ->", os.path.abspath(OUT))
