"""
Generates watchface/src/main/res/raw/watchface.xml (Watch Face Format v4).

    python tools/gen_watchface.py

Draw order (back to front)
  hintergrund        pre-rendered static layer (stars, orbits, belt, sun + glow, ticks, battery track)
  komet              static comet (setting "Komet")
  ListConfiguration "modus"  -> one solar system per mode
      uhrwerk: Neptune = 24 h, the others scaled from the real period ratios
      echt:    real heliocentric longitudes of today
    aktiv  (hidden in ambient)
      glowing trails (stacked arcs), Earth's trail = step progress
      Mercury / Venus / Earth when behind the sun
      sonne_overlay (sun crop, hides what is behind it)
      Mercury / Venus / Earth in front, Mars, Jupiter + moons, Saturn, Uranus, Neptune
    ambient (only in ambient): orbit lines, sun ring, planet outlines
  battery fill, time, date + moon phase, heart rate / steps / battery
"""
import math
import os
import sys
import xml.etree.ElementTree as ET

from PIL import ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from config import *  # noqa

HERE = os.path.dirname(__file__)
RES = os.path.join(HERE, "..", "watchface", "src", "main", "res")
OUT = os.path.join(RES, "raw", "watchface.xml")

S = ET.SubElement

# ---- text styles of the reference image (canvas px) -------------------------
TIME_FONT, TIME_SIZE, TIME_LS, TIME_BASE = "inter_display_extralight", 74.0, 0.03, 118
SMALL_FONT, DATE_SIZE, ROW_SIZE = "inter_regular", 16.0, 17.0
DATE_LS, ROW_LS = 0.16, 0.06
DATE_BASE, ROW_BASE = 148, 394
ROW_X = (140, 225, 310)          # centres of heart rate / steps / battery
COL_TIME, COL_GOLD, COL_ROW, COL_STEPS = "#FFF0ECE4", "#FFDCBE87", "#FFC8C4BC", "#FF96D7F0"
COL_TIME_AOD, COL_DATE_AOD = "#FFAF9669", "#FF6E5F46"

# ---- trail arcs (calibrated against the reference splat, see README) ---------
TRAIL_COLOR, TRAIL_BASE = (0.95, 0.88, 0.75), 0.035
EARTH_COLOR = (0.55, 0.88, 1.0)
TRAIL_W = 1.6


def attrs(**kw):
    return {k: (fmt(v) if isinstance(v, (int, float)) else str(v)) for k, v in kw.items()}


def group(parent, name, x=0, y=0, w=CANVAS, h=CANVAS, **kw):
    return S(parent, "Group", attrs(name=name, x=x, y=y, width=w, height=h, **kw))


def tf(parent, target, value):
    return S(parent, "Transform", dict(target=target, value=value))


def image(parent, res, x, y, w, h, **kw):
    pi = S(parent, "PartImage", attrs(x=x, y=y, width=w, height=h, **kw))
    S(pi, "Image", dict(resource=res))
    return pi


def ambient_hide(el):
    S(el, "Variant", dict(mode="AMBIENT", target="alpha", value="0"))


def ambient_only(el):
    el.set("alpha", "0")
    S(el, "Variant", dict(mode="AMBIENT", target="alpha", value="255"))


def condition(parent, exprs):
    c = S(parent, "Condition")
    ex = S(c, "Expressions")
    for n, e in exprs:
        S(ex, "Expression", dict(name=n)).text = e
    return c, {n: S(c, "Compare", dict(expression=n)) for n, _ in exprs}


def frames(parent, prefix, lam, x, y, size):
    """24 pre-lit frames, the one matching the current longitude is drawn"""
    idx = frame_index_expr(lam)
    _, comps = condition(parent, [(f"f{k}", f"{idx} == {k}") for k in range(N_FRAMES)])
    for k in range(N_FRAMES):
        image(comps[f"f{k}"], f"{prefix}_{k:02d}", x, y, size, size)


def argb(rgb, a):
    return "#" + "".join(f"{int(round(max(0, min(1, v)) * 255)):02X}" for v in (a, *rgb))


# ----------------------------------------------------------------------------- bodies
def moon_group(parent, name, mu, r, ms, gs, frame_lam=None, res=None):
    g = group(parent, name, 0, 0, ms, ms)
    tf(g, "x", f"{fmt(gs / 2 - ms / 2)} + {fmt(r)} * cos(rad({mu}))")
    tf(g, "y", f"{fmt(gs / 2 - ms / 2)} - {fmt(r * K)} * sin(rad({mu}))")
    if frame_lam is not None:
        frames(g, "mond", frame_lam, 0, 0, ms)
    else:
        image(g, res, 0, 0, ms, ms)


def planet_group(parent, p, mode):
    lam = lam_expr(p, mode)
    s = sprite_size(p)
    moons = []
    if p["key"] == "erde":
        moons = [("mond", moon_expr(mode), MOON["r"], small_sprite(MOON["R"]), True, None)]
    if p["key"] == "jupiter":
        moons = [(g["key"], galilean_expr(g, mode), g["r"], small_sprite(g["R"]), False, f"mond_{g['key']}")
                 for g in GALILEAN]
    gs = s
    for _, _, r, ms, _, _ in moons:
        gs = max(gs, int(math.ceil(2 * (r + ms))) | 1)
    g = group(parent, p["key"], 0, 0, gs, gs, pivotX=0.5, pivotY=0.5)
    tf(g, "x", f"{sx_expr(lam, p['r'])} - {fmt(gs / 2)}")
    tf(g, "y", f"{sy_expr(lam, p['r'])} - {fmt(gs / 2)}")
    d = depth_scale_expr(lam, p["r"])
    tf(g, "scaleX", d)
    tf(g, "scaleY", d)

    def add_moons(front):
        for name, mu, r, ms, lit, res in moons:
            key = "v" if front else "h"
            _, comps = condition(g, [(key, near_expr(mu) if front else far_expr(mu))])
            moon_group(comps[key], name, mu, r, ms, gs, frame_lam=lam if lit else None, res=res)

    add_moons(False)
    frames(g, p["key"], lam, (gs - s) // 2, (gs - s) // 2, s)
    add_moons(True)


def stacked_alphas(breaks, target, base, c):
    """alpha per arc so that the stacked arcs reproduce `target(b)` (display value) over `base`.
    Arc k spans 0..breaks[k] behind the planet; segment j is covered by arcs k >= j."""
    A = []
    lo = 0
    for hi in breaks:
        mid = (lo + hi) / 2
        A.append(max(0.0, min(0.95, (target(mid) - base) / (c - base))))
        lo = hi
    a = [0.0] * len(breaks)
    nxt = 0.0
    for j in range(len(breaks) - 1, -1, -1):
        a[j] = max(0.0, 1 - (1 - A[j]) / (1 - nxt)) if nxt < 1 else 0.0
        nxt = A[j]
    return a


def trail_arcs(parent, p, mode):
    """glowing trail behind the planet: stacked arcs on the orbit ellipse.
    WFF arc angle a (0 = 12 o'clock, clockwise) <-> screen longitude: a = 90 - lambda.
    The planets move clockwise (lambda decreases), so 'behind' = smaller a."""
    lam = lam_expr(p, mode)
    r = p["r"]
    pd = S(parent, "PartDraw", attrs(x=0, y=0, width=CANVAS, height=CANVAS, name=f"spur_{p['key']}"))
    a_head = f"(90 - {lam})"
    if p["key"] == "erde":
        breaks = [10, 25, 45, 70, 100, 140, 200, 360]
        alphas = stacked_alphas(breaks, lambda b: 0.30 + 0.40 * math.exp(-b / 50), 0.04, EARTH_COLOR[1])
        color = EARTH_COLOR
    else:
        breaks = [6, 14, 24, 36, 50, 68, 92, 125]
        alphas = stacked_alphas(breaks, lambda b: TRAIL_BASE + (0.42 - TRAIL_BASE) * math.exp(-b / 40),
                                TRAIL_BASE, TRAIL_COLOR[1])
        color = TRAIL_COLOR
    for L, a in zip(breaks, alphas):
        if a < 0.004:
            continue
        arc = S(pd, "Arc", attrs(centerX=SUN_X, centerY=SUN_Y, width=2 * r, height=2 * r * K,
                                 startAngle=0, endAngle=1))
        S(arc, "Stroke", attrs(color=argb(color, a), thickness=TRAIL_W, cap="BUTT"))
        if p["key"] == "erde":
            length = f"clamp(3.6 * clamp([STEP_PERCENT], 0, 100), 0, {L})"
        else:
            length = str(L)
        tf(arc, "startAngle", f"{a_head} - {length}")
        tf(arc, "endAngle", a_head)


def system(parent, mode):
    sysg = group(parent, f"system_{mode}")
    act = group(sysg, "aktiv")
    ambient_hide(act)
    for p in PLANETS:
        trail_arcs(act, p, mode)
    behind = [p for p in PLANETS if p["behind"]]
    for p in behind:
        _, comps = condition(act, [("hinten", far_expr(lam_expr(p, mode)))])
        planet_group(comps["hinten"], p, mode)
    image(act, "sonne_overlay", int(SUN_X - SUN_OVERLAY / 2), int(SUN_Y - SUN_OVERLAY / 2), SUN_OVERLAY, SUN_OVERLAY)
    for p in behind:
        _, comps = condition(act, [("vorne", near_expr(lam_expr(p, mode)))])
        planet_group(comps["vorne"], p, mode)
    for p in PLANETS:
        if not p["behind"]:
            planet_group(act, p, mode)

    amb = group(sysg, "ambient")
    ambient_only(amb)
    pd = S(amb, "PartDraw", attrs(x=0, y=0, width=CANVAS, height=CANVAS))
    for p in PLANETS:
        r = p["r"]
        el = S(pd, "Ellipse", attrs(x=SUN_X - r, y=SUN_Y - r * K, width=2 * r, height=2 * r * K))
        S(el, "Stroke", attrs(color="#FF26221C", thickness=0.6))
    el = S(pd, "Ellipse", attrs(x=SUN_X - SUN_R, y=SUN_Y - SUN_R, width=2 * SUN_R, height=2 * SUN_R))
    S(el, "Stroke", attrs(color="#FF96805A", thickness=1.0))
    for p in PLANETS:
        lam = lam_expr(p, mode)
        d = max(3, int(round(p["R"])) | 1)
        o = S(amb, "PartDraw", attrs(x=0, y=0, width=d + 2, height=d + 2, name=f"aod_{p['key']}"))
        tf(o, "x", f"{sx_expr(lam, p['r'])} - {fmt(d / 2 + 1)}")
        tf(o, "y", f"{sy_expr(lam, p['r'])} - {fmt(d / 2 + 1)}")
        e = S(o, "Ellipse", attrs(x=1, y=1, width=d, height=d))
        S(e, "Stroke", attrs(color="#FF96805A", thickness=0.6))


# ----------------------------------------------------------------------------- text
_fonts = {}


def metrics(family, size):
    key = (family, size)
    if key not in _fonts:
        f = ImageFont.truetype(os.path.join(RES, "font", family + ".otf"), 1000)
        asc, desc = f.getmetrics()
        _fonts[key] = (asc / 1000 * size, desc / 1000 * size)
    return _fonts[key]


def text(parent, cx, baseline, w, family, size, color, template, params=(), letter=None, upper=False,
         align="CENTER", name=None):
    """PartText positioned by the text baseline (box height = ascent + descent)"""
    asc, desc = metrics(family, size)
    x = {"CENTER": cx - w / 2, "START": cx, "END": cx - w}[align]
    a = dict(x=int(round(x)), y=int(round(baseline - asc)), width=int(w), height=int(math.ceil(asc + desc)))
    if name:
        a["name"] = name
    pt = S(parent, "PartText", attrs(**a))
    t = S(pt, "Text", dict(align=align))
    fa = dict(family=family, size=size, color=color)
    if letter:
        fa["letterSpacing"] = round(letter, 4)
    f = S(t, "Font", attrs(**fa))
    holder = S(f, "Upper") if upper else f
    if not params:
        holder.text = template
        return pt
    tp = S(holder, "Template")
    tp.text = template
    for p in params:
        S(tp, "Parameter", dict(expression=p))
    return pt


def time_text(parent, color, ambient):
    g = group(parent, "zeit_aod" if ambient else "zeit")
    (ambient_only if ambient else ambient_hide)(g)
    _, comps = condition(g, [("h24", "[IS_24_HOUR_MODE]")])
    text(comps["h24"], 225, TIME_BASE, 320, TIME_FONT, TIME_SIZE, color, "%s:%s", ("[HOUR_0_23_Z]", "[MINUTE_Z]"),
         letter=TIME_LS)
    d = S(g.find("Condition"), "Default")
    text(d, 225, TIME_BASE, 320, TIME_FONT, TIME_SIZE, color, "%s:%s", ("[HOUR_1_12]", "[MINUTE_Z]"), letter=TIME_LS)


def date_width(sample="MO  ·  9 NOV"):
    f = ImageFont.truetype(os.path.join(RES, "font", SMALL_FONT + ".otf"), 1000)
    w = sum(f.getlength(c) for c in sample) / 1000 * DATE_SIZE + DATE_LS * DATE_SIZE * (len(sample) - 1)
    digit = f.getlength("0") / 1000 * DATE_SIZE + DATE_LS * DATE_SIZE
    return w, digit


DATE_CX = 225 - (MOONPHASE_ICON + 7) / 2       # date + moon icon centred as a unit


def date_text(parent, color, ambient):
    t = text(parent, DATE_CX, DATE_BASE, 240, SMALL_FONT, DATE_SIZE, color, "%s  ·  %s %s",
             ("subText([DAY_OF_WEEK_S], 0, 2)", "[DAY]", "subText([MONTH_S], 0, 3)"), letter=DATE_LS, upper=True,
             name="datum_aod" if ambient else "datum")
    (ambient_only if ambient else ambient_hide)(t)


def build():
    wf = ET.Element("WatchFace", attrs(width=CANVAS, height=CANVAS, clipShape="CIRCLE"))
    S(wf, "Metadata", dict(key="CLOCK_TYPE", value="DIGITAL"))
    S(wf, "Metadata", dict(key="PREVIEW_TIME", value="22:59:30"))
    uc = S(wf, "UserConfigurations")
    lc = S(uc, "ListConfiguration", dict(id="modus", displayName="cfg_modus", defaultValue="uhrwerk"))
    S(lc, "ListOption", dict(id="uhrwerk", displayName="cfg_modus_uhrwerk"))
    S(lc, "ListOption", dict(id="echt", displayName="cfg_modus_echt"))
    S(uc, "BooleanConfiguration", dict(id="komet", displayName="cfg_komet", defaultValue="TRUE"))

    sc = S(wf, "Scene", dict(backgroundColor="#FF000000"))
    bg = image(sc, "hintergrund", 0, 0, CANVAS, CANVAS, name="hintergrund")
    ambient_hide(bg)

    kx, ky, kw, kh = (float(v) for v in open(os.path.join(HERE, "komet_box.txt")).read().split())
    bc = S(sc, "BooleanConfiguration", dict(id="komet"))
    on = S(bc, "BooleanOption", dict(id="TRUE"))
    k = image(on, "komet", int(kx), int(ky), int(kw), int(kh), name="komet")
    ambient_hide(k)
    group(S(bc, "BooleanOption", dict(id="FALSE")), "komet_aus", 0, 0, 1, 1)

    lc = S(sc, "ListConfiguration", dict(id="modus"))
    for mode in MODES:
        system(S(lc, "ListOption", dict(id=mode)), mode)

    # battery: filled part of the arc at the bottom (the track is in the background)
    pd = S(sc, "PartDraw", attrs(x=0, y=0, width=CANVAS, height=CANVAS, name="akku"))
    ambient_hide(pd)
    arc = S(pd, "Arc", attrs(centerX=FACE_C, centerY=FACE_C, width=2 * BATTERY_R, height=2 * BATTERY_R,
                             startAngle=BATTERY_A0, endAngle=BATTERY_A1))
    S(arc, "Stroke", attrs(color="#FFE4CB96", thickness=1.8, cap="BUTT"))
    tf(arc, "startAngle", f"{fmt(BATTERY_A1)} - {fmt((BATTERY_A1 - BATTERY_A0) / 100)} * clamp([BATTERY_PERCENT], 0, 100)")

    time_text(sc, COL_TIME, False)
    time_text(sc, COL_TIME_AOD, True)
    date_text(sc, COL_GOLD, False)
    date_text(sc, COL_DATE_AOD, True)

    w, digit = date_width()
    ix = int(round(DATE_CX + w / 2 + 7))
    iy = int(round(DATE_BASE - 0.73 * DATE_SIZE / 2 - MOONPHASE_ICON / 2))
    mg = group(sc, "mondphase", ix, iy, MOONPHASE_ICON, MOONPHASE_ICON)
    tf(mg, "x", f"{ix} + ([DAY] > 9 ? {fmt(round(digit / 2, 2))} : 0)")
    ambient_hide(mg)
    _, comps = condition(mg, [(f"m{k}", f"[MOON_PHASE_TYPE] == {k}") for k in range(8)])
    for k in range(8):
        image(comps[f"m{k}"], f"mondphase_{k}", 0, 0, MOONPHASE_ICON, MOONPHASE_ICON)

    row = group(sc, "werte")
    ambient_hide(row)
    _, comps = condition(row, [("hr_ok", "[HEART_RATE] > 0")])
    hx, sx_, bx = ROW_X
    text(comps["hr_ok"], hx, ROW_BASE, 90, SMALL_FONT, ROW_SIZE, COL_ROW, "%s BPM", ("[HEART_RATE]",), letter=ROW_LS)
    text(S(row.find("Condition"), "Default"), hx, ROW_BASE, 90, SMALL_FONT, ROW_SIZE, "#FF8A867E", "-- BPM",
         letter=ROW_LS)
    text(row, sx_, ROW_BASE, 70, SMALL_FONT, ROW_SIZE, COL_STEPS, "%s", ("[STEP_COUNT]",), letter=ROW_LS)
    text(row, bx, ROW_BASE, 90, SMALL_FONT, ROW_SIZE, COL_ROW, "%s %%", ("[BATTERY_PERCENT]",), letter=ROW_LS)
    dots = S(row, "PartDraw", attrs(x=0, y=0, width=CANVAS, height=CANVAS))
    for x in ((hx + sx_) / 2 + 2, (sx_ + bx) / 2 - 2):
        e = S(dots, "Ellipse", attrs(x=x - 1.3, y=ROW_BASE - 7.5, width=2.6, height=2.6))
        S(e, "Fill", dict(color=COL_GOLD))
    return wf


def serialize(wf):
    ET.indent(wf, space="  ")
    for el in wf.iter():                     # Font / Upper / Template content is whitespace sensitive
        if el.tag in ("Font", "Upper") and len(el):
            el.text = None
            for c in el:
                c.tail = None
        if el.tag == "Template":
            for c in el:
                c.tail = None
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!-- GENERATED by tools/gen_watchface.py - edit the generator, not this file. -->\n'
            + ET.tostring(wf, encoding="unicode") + "\n")


if __name__ == "__main__":
    xml = serialize(build())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"{OUT}: {len(xml) / 1024:.1f} KiB")
