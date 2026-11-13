"""
Shared WFF building blocks for the watch faces:
  * selectable time font (UserConfiguration "schrift", 5 bundled OFL fonts)
  * complication slots ("Datenfelder") the user fills on the watch:
      round_slot()  round field with value ring  (RANGED_VALUE, GOAL_PROGRESS, SHORT_TEXT, icons)
      long_slot()   wide pill for LONG_TEXT       (next event, music, ...)
      row_slot()    plain text field for a row     (SHORT_TEXT, RANGED_VALUE, GOAL_PROGRESS)

Usage: from ui_common import *  (needs RES = path to watchface/src/main/res)
"""
import math
import os
import xml.etree.ElementTree as ET

from PIL import ImageFont

S = ET.SubElement

# id, string resource, font family (res/font file name without extension), letter spacing (em)
FONTS = [
    ("klassisch", "schrift_klassisch", "inter_display_extralight", 0.03),
    ("kraeftig", "schrift_kraeftig", "inter_display_semibold", 0.0),
    ("futuristisch", "schrift_futuristisch", "orbitron_regular", 0.0),
    ("technisch", "schrift_technisch", "jetbrains_mono_light", -0.02),
    ("elegant", "schrift_elegant", "playfair_display", 0.0),
]
SMALL_FONT = "inter_regular"
REF_FAMILY, REF_SIZE = "inter_display_extralight", 74.0


def _fmt(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def A(**kw):
    return {k: _fmt(v) for k, v in kw.items()}


def font_file(res, family):
    for ext in (".otf", ".ttf"):
        p = os.path.join(res, "font", family + ext)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(family)


def metrics(res, family, size):
    f = ImageFont.truetype(font_file(res, family), 1000)
    a, d = f.getmetrics()
    return a / 1000 * size, d / 1000 * size


def time_size(res, family, ls):
    """size for `family` so the time has the same width as the reference ("00:00"),
    without getting taller than the reference digits"""
    def width(fam, size, l):
        f = ImageFont.truetype(font_file(res, fam), 1000)
        return (sum(f.getlength(c) for c in "00:00") / 1000 + l * 4) * size

    def cap(fam, size):
        f = ImageFont.truetype(font_file(res, fam), 1000)
        b = f.getbbox("0")
        return (b[3] - b[1]) / 1000 * size
    w_ref = width(REF_FAMILY, REF_SIZE, 0.03)
    s = REF_SIZE * w_ref / width(family, REF_SIZE, ls)
    s = min(s, REF_SIZE * cap(REF_FAMILY, REF_SIZE) / cap(family, REF_SIZE) * 1.04)
    return round(s, 1)


def text(res, parent, cx, base, w, family, size, color, template, params=(), ls=None, upper=False,
         align="CENTER", ellipsis=False, x=None):
    """PartText placed by baseline; box height = ascent + descent"""
    asc, desc = metrics(res, family, size)
    left = x if x is not None else {"CENTER": cx - w / 2, "START": cx, "END": cx - w}[align]
    pt = S(parent, "PartText", A(x=int(round(left)), y=int(round(base - asc)), width=int(w),
                                 height=int(math.ceil(asc + desc))))
    ta = dict(align=align)
    if ellipsis:
        ta["ellipsis"] = "TRUE"
    t = S(pt, "Text", ta)
    fa = dict(family=family, size=size, color=color)
    if ls:
        fa["letterSpacing"] = ls
    f = S(t, "Font", A(**fa))
    h = S(f, "Upper") if upper else f
    if not params:
        h.text = template
        return pt
    tp = S(h, "Template")
    tp.text = template
    for p in params:
        S(tp, "Parameter", dict(expression=p))
    return pt


# ----------------------------------------------------------------------------- fonts
def add_font_config(user_configs):
    lc = S(user_configs, "ListConfiguration", dict(id="schrift", displayName="cfg_schrift", defaultValue="klassisch"))
    for fid, name, _, _ in FONTS:
        S(lc, "ListOption", dict(id=fid, displayName=name))


def time_block(res, scene, base, color, color_aod, width=330):
    """time in the selected font (active + ambient variant); 24 h / 12 h follows the phone"""
    lc = S(scene, "ListConfiguration", dict(id="schrift"))
    for fid, _, family, ls in FONTS:
        opt = S(lc, "ListOption", dict(id=fid))
        g = S(opt, "Group", A(name=f"zeit_{fid}", x=0, y=0, width=450, height=450))
        size = time_size(res, family, ls)
        for amb in (False, True):
            sub = S(g, "Group", A(name=f"zeit_{fid}_{'aod' if amb else 'aktiv'}", x=0, y=0, width=450, height=450,
                                  alpha=0 if amb else 255))
            S(sub, "Variant", dict(mode="AMBIENT", target="alpha", value="255" if amb else "0"))
            c = S(sub, "Condition")
            ex = S(c, "Expressions")
            S(ex, "Expression", dict(name="h24")).text = "[IS_24_HOUR_MODE]"
            col = color_aod if amb else color
            text(res, S(c, "Compare", dict(expression="h24")), 225, base, width, family, size, col, "%s:%s",
                 ("[HOUR_0_23_Z]", "[MINUTE_Z]"), ls=ls)
            text(res, S(c, "Default"), 225, base, width, family, size, col, "%s:%s",
                 ("[HOUR_1_12]", "[MINUTE_Z]"), ls=ls)


# ----------------------------------------------------------------------------- complications
TXT = "[COMPLICATION.TEXT]"
TTL = "[COMPLICATION.TITLE]"
IMG = "[COMPLICATION.MONOCHROMATIC_IMAGE]"
SIMG = "[COMPLICATION.SMALL_IMAGE]"


def _ranged_frac():
    v, lo, hi = "[COMPLICATION.RANGED_VALUE_VALUE]", "[COMPLICATION.RANGED_VALUE_MIN]", "[COMPLICATION.RANGED_VALUE_MAX]"
    return f"((clamp({v}, {lo}, {hi}) - {lo}) / ({hi} - {lo}))"


def _goal_frac():
    v, t = "[COMPLICATION.GOAL_PROGRESS_VALUE]", "[COMPLICATION.GOAL_PROGRESS_TARGET_VALUE]"
    return f"clamp({v} / {t}, 0, 1)"


def _slot(scene, slot_id, name, x, y, w, h, types, provider, provider_type, bounding="oval", corner=0):
    cs = S(scene, "ComplicationSlot", A(slotId=slot_id, name=name, displayName=name, x=x, y=y, width=w, height=h,
                                        supportedTypes=" ".join(types), isCustomizable=True))
    S(cs, "DefaultProviderPolicy", dict(defaultSystemProvider=provider, defaultSystemProviderType=provider_type))
    if bounding == "oval":
        S(cs, "BoundingOval", A(x=0, y=0, width=w, height=h, outlinePadding=2))
    else:
        S(cs, "BoundingRoundBox", A(x=0, y=0, width=w, height=h, cornerRadius=corner, outlinePadding=2))
    S(cs, "Variant", dict(mode="AMBIENT", target="alpha", value="0"))
    return cs


def _icon(parent, x, y, s, color, src=IMG):
    pi = S(parent, "PartImage", A(x=int(round(x)), y=int(round(y)), width=int(s), height=int(s), tintColor=color))
    S(pi, "Image", dict(resource=src))


def _round_content(res, comp, d, accent, fg, frac=None):
    """inside of a round field: optional value ring, then icon / text / title"""
    pd = S(comp, "PartDraw", A(x=0, y=0, width=d, height=d))
    e = S(pd, "Ellipse", A(x=1, y=1, width=d - 2, height=d - 2))
    S(e, "Fill", dict(color="#9E000000"))
    if frac is not None:
        r = d - 6
        track = S(pd, "Arc", A(centerX=d / 2, centerY=d / 2, width=r, height=r, startAngle=0, endAngle=360))
        S(track, "Stroke", A(color="#40" + accent[3:], thickness=2.2, cap="BUTT"))
        arc = S(pd, "Arc", A(centerX=d / 2, centerY=d / 2, width=r, height=r, startAngle=0, endAngle=360))
        S(arc, "Stroke", A(color=accent, thickness=2.2, cap="ROUND"))
        S(arc, "Transform", dict(target="endAngle", value=f"360 * {frac}"))
    else:
        e2 = S(pd, "Ellipse", A(x=3, y=3, width=d - 6, height=d - 6))
        S(e2, "Stroke", A(color="#55" + accent[3:], thickness=1.2))
    c = S(comp, "Condition")
    ex = S(c, "Expressions")
    cases = [("txt_ttl", f"{TXT} != null && {TTL} != null"),
             ("img_txt", f"{IMG} != null && {TXT} != null"),
             ("txt", f"{TXT} != null"),
             ("img", f"{IMG} != null")]
    for n, e_ in cases:
        S(ex, "Expression", dict(name=n)).text = e_
    cmp = {n: S(c, "Compare", dict(expression=n)) for n, _ in cases}
    cy = d / 2
    text(res, cmp["txt_ttl"], d / 2, cy + 3, d - 12, SMALL_FONT, 15, fg, "%s", (TXT,), ellipsis=True)
    text(res, cmp["txt_ttl"], d / 2, cy + 15, d - 16, SMALL_FONT, 9.5, accent, "%s", (TTL,), upper=True, ellipsis=True,
         ls=0.06)
    _icon(cmp["img_txt"], d / 2 - 7, cy - 17, 14, accent)
    text(res, cmp["img_txt"], d / 2, cy + 12, d - 12, SMALL_FONT, 15, fg, "%s", (TXT,), ellipsis=True)
    text(res, cmp["txt"], d / 2, cy + 6, d - 12, SMALL_FONT, 16, fg, "%s", (TXT,), ellipsis=True)
    _icon(cmp["img"], d / 2 - 11, cy - 11, 22, fg)
    if frac is not None:   # ranged value without any text: show the number itself
        dflt = S(c, "Default")
        v = "[COMPLICATION.RANGED_VALUE_VALUE]" if "RANGED" in frac else "[COMPLICATION.GOAL_PROGRESS_VALUE]"
        text(res, dflt, d / 2, cy + 6, d - 12, SMALL_FONT, 16, fg, "%s", (f"round({v})",))


def round_slot(res, scene, slot_id, name, cx, cy, d, provider, provider_type, accent, fg="#FFF0ECE4"):
    x, y = int(round(cx - d / 2)), int(round(cy - d / 2))
    types = ["RANGED_VALUE", "GOAL_PROGRESS", "SHORT_TEXT", "MONOCHROMATIC_IMAGE", "SMALL_IMAGE", "EMPTY"]
    cs = _slot(scene, slot_id, name, x, y, d, d, types, provider, provider_type)
    _round_content(res, S(cs, "Complication", dict(type="RANGED_VALUE")), d, accent, fg, frac=_ranged_frac())
    _round_content(res, S(cs, "Complication", dict(type="GOAL_PROGRESS")), d, accent, fg, frac=_goal_frac())
    _round_content(res, S(cs, "Complication", dict(type="SHORT_TEXT")), d, accent, fg)
    comp = S(cs, "Complication", dict(type="MONOCHROMATIC_IMAGE"))
    _round_content(res, comp, d, accent, fg)
    comp = S(cs, "Complication", dict(type="SMALL_IMAGE"))
    pd = S(comp, "PartDraw", A(x=0, y=0, width=d, height=d))
    S(S(pd, "Ellipse", A(x=1, y=1, width=d - 2, height=d - 2)), "Fill", dict(color="#9E000000"))
    pi = S(comp, "PartImage", A(x=int(d / 2 - 14), y=int(d / 2 - 14), width=28, height=28))
    S(pi, "Image", dict(resource=SIMG))
    S(cs, "Complication", dict(type="EMPTY"))
    return cs


def long_slot(res, scene, slot_id, name, cx, cy, w, h, provider, provider_type, accent, fg="#FFE6E2DA"):
    x, y = int(round(cx - w / 2)), int(round(cy - h / 2))
    cs = _slot(scene, slot_id, name, x, y, w, h, ["LONG_TEXT", "SHORT_TEXT", "EMPTY"], provider, provider_type,
               bounding="box", corner=h / 2)
    for typ in ("LONG_TEXT", "SHORT_TEXT"):
        comp = S(cs, "Complication", dict(type=typ))
        pd = S(comp, "PartDraw", A(x=0, y=0, width=w, height=h))
        rr = S(pd, "RoundRectangle", A(x=0, y=0, width=w, height=h, cornerRadiusX=h / 2, cornerRadiusY=h / 2))
        S(rr, "Fill", dict(color="#8C000000"))
        c = S(comp, "Condition")
        ex = S(c, "Expressions")
        S(ex, "Expression", dict(name="ttl")).text = f"{TTL} != null && {TXT} != null"
        S(ex, "Expression", dict(name="img")).text = f"{IMG} != null && {TXT} != null"
        S(ex, "Expression", dict(name="txt")).text = f"{TXT} != null"
        base = h / 2 + 5.5
        t = S(c, "Compare", dict(expression="ttl"))
        text(res, t, w / 2, base, w - 24, SMALL_FONT, 15, fg, "%s  %s", (TTL, TXT), ellipsis=True)
        t = S(c, "Compare", dict(expression="img"))
        _icon(t, 12, h / 2 - 8, 16, accent)
        text(res, t, w / 2 + 8, base, w - 44, SMALL_FONT, 15, fg, "%s", (TXT,), ellipsis=True)
        t = S(c, "Compare", dict(expression="txt"))
        text(res, t, w / 2, base, w - 24, SMALL_FONT, 15, fg, "%s", (TXT,), ellipsis=True)
    S(cs, "Complication", dict(type="EMPTY"))
    return cs


def row_slot(res, scene, slot_id, name, cx, base, w, provider, provider_type, color, accent):
    """text-only field for a data row (Sonnensystem): value centred on cx, baseline `base`"""
    asc, desc = metrics(res, SMALL_FONT, 17)
    h = int(math.ceil(asc + desc)) + 4
    x, y = int(round(cx - w / 2)), int(round(base - asc - 2))
    types = ["SHORT_TEXT", "RANGED_VALUE", "GOAL_PROGRESS", "MONOCHROMATIC_IMAGE", "EMPTY"]
    cs = _slot(scene, slot_id, name, x, y, w, h, types, provider, provider_type, bounding="box", corner=6)
    lb = asc + 2                                   # baseline inside the slot
    for typ in ("SHORT_TEXT", "RANGED_VALUE", "GOAL_PROGRESS"):
        comp = S(cs, "Complication", dict(type=typ))
        c = S(comp, "Condition")
        ex = S(c, "Expressions")
        S(ex, "Expression", dict(name="ttl")).text = f"{TXT} != null && {TTL} != null"
        S(ex, "Expression", dict(name="img")).text = f"{TXT} != null && {IMG} != null"
        S(ex, "Expression", dict(name="txt")).text = f"{TXT} != null"
        text(res, S(c, "Compare", dict(expression="ttl")), w / 2, lb, w, SMALL_FONT, 17, color, "%s %s", (TXT, TTL),
             ls=0.06, upper=True, ellipsis=True)
        t = S(c, "Compare", dict(expression="img"))
        _icon(t, w / 2 - 25, lb - 13, 14, accent)           # icon directly in front of the value
        text(res, t, w / 2 - 7, lb, w / 2 + 7, SMALL_FONT, 17, color, "%s", (TXT,), ls=0.06, ellipsis=True,
             align="START")
        text(res, S(c, "Compare", dict(expression="txt")), w / 2, lb, w, SMALL_FONT, 17, color, "%s", (TXT,), ls=0.06,
             ellipsis=True)
        if typ != "SHORT_TEXT":
            v = "[COMPLICATION.RANGED_VALUE_VALUE]" if typ == "RANGED_VALUE" else "[COMPLICATION.GOAL_PROGRESS_VALUE]"
            text(res, S(c, "Default"), w / 2, lb, w, SMALL_FONT, 17, color, "%s", (f"round({v})",), ls=0.06)
    comp = S(cs, "Complication", dict(type="MONOCHROMATIC_IMAGE"))
    _icon(comp, w / 2 - 8, lb - 14, 16, color)
    S(cs, "Complication", dict(type="EMPTY"))
    return cs


STRINGS_DE = {
    "cfg_schrift": "Schriftart",
    "schrift_klassisch": "Klassisch",
    "schrift_kraeftig": "Kräftig",
    "schrift_futuristisch": "Futuristisch",
    "schrift_technisch": "Technisch",
    "schrift_elegant": "Elegant",
    "feld_links": "Feld links",
    "feld_mitte": "Feld Mitte",
    "feld_rechts": "Feld rechts",
    "feld_unten": "Feld unten",
}
STRINGS_EN = {
    "cfg_schrift": "Font",
    "schrift_klassisch": "Classic",
    "schrift_kraeftig": "Bold",
    "schrift_futuristisch": "Futuristic",
    "schrift_technisch": "Technical",
    "schrift_elegant": "Elegant",
    "feld_links": "Left field",
    "feld_mitte": "Centre field",
    "feld_rechts": "Right field",
    "feld_unten": "Bottom field",
}
