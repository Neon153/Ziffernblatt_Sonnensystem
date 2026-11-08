"""
Offline preview renderer for watchface.xml.

Parses the generated XML, evaluates every WFF expression with its own parser and renders
the scene with PIL. It supports exactly the subset of WFF this watch face uses (Group,
PartImage, PartDraw Ellipse/Arc/Line, PartText, DigitalClock, Condition, ListConfiguration,
BooleanConfiguration, Transform, Variant AMBIENT, blendMode PLUS). Its purpose is to check
the logic of the XML (positions, frame selection, depth order, ambient mode) without a watch.

    python tools/simulate.py preview            -> res/drawable-nodpi/preview.png
    python tools/simulate.py gallery            -> build/sim/*.png + animation
"""
import datetime as dt
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from config import CANVAS  # noqa

ROOT = os.path.join(os.path.dirname(__file__), "..")
RES = os.path.join(ROOT, "watchface", "src", "main", "res")
XML = os.path.join(RES, "raw", "watchface.xml")
SS = 2  # supersampling of the whole canvas


# ============================================================================ expressions
TOKEN = re.compile(r"\s*(?:(\d+\.\d*|\.\d+|\d+)|(\[[A-Z0-9_.]+\])|([A-Za-z_]\w*)|(&&|\|\||>=|<=|==|!=|[-+*/%(),?:<>!]))")
FUNCS = dict(
    sin=math.sin, cos=math.cos, tan=math.tan, asin=math.asin, acos=math.acos, atan=math.atan,
    abs=abs, floor=math.floor, ceil=math.ceil, round=round, sqrt=math.sqrt, exp=math.exp,
    log=math.log, pow=math.pow, rad=math.radians, deg=math.degrees,
    fract=lambda x: x - math.floor(x), clamp=lambda x, a, b: max(a, min(b, x)),
    subText=lambda s, a, b: str(s)[int(a):int(b)],
)


class Expr:
    def __init__(self, src):
        self.toks = []
        pos = 0
        src = src.strip()
        while pos < len(src):
            m = TOKEN.match(src, pos)
            if not m:
                raise SyntaxError(f"bad token at {src[pos:pos + 20]!r}")
            self.toks.append(next(g for g in m.groups() if g is not None))
            pos = m.end()
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, t=None):
        tok = self.peek()
        if t is not None and tok != t:
            raise SyntaxError(f"expected {t}, got {tok}")
        self.i += 1
        return tok

    def parse(self):
        node = self.ternary()
        if self.peek() is not None:
            raise SyntaxError(f"trailing {self.peek()}")
        return node

    def ternary(self):
        c = self.orr()
        if self.peek() == "?":
            self.take()
            a = self.ternary(); self.take(":"); b = self.ternary()
            return ("?", c, a, b)
        return c

    def binary(self, sub, ops):
        n = sub()
        while self.peek() in ops:
            op = self.take(); n = (op, n, sub())
        return n

    def orr(self): return self.binary(self.andd, ("||",))
    def andd(self): return self.binary(self.eq, ("&&",))
    def eq(self): return self.binary(self.rel, ("==", "!="))
    def rel(self): return self.binary(self.add, (">", ">=", "<", "<="))
    def add(self): return self.binary(self.mul, ("+", "-"))
    def mul(self): return self.binary(self.unary, ("*", "/", "%"))

    def unary(self):
        if self.peek() in ("-", "!", "+"):
            op = self.take(); return ("u" + op, self.unary())
        return self.atom()

    def atom(self):
        t = self.take()
        if t == "(":
            n = self.ternary(); self.take(")"); return n
        if t.startswith("["):
            return ("src", t[1:-1])
        if re.match(r"[\d.]", t):
            return ("num", float(t))
        if self.peek() == "(":
            self.take(); args = []
            if self.peek() != ")":
                args.append(self.ternary())
                while self.peek() == ",":
                    self.take(); args.append(self.ternary())
            self.take(")")
            return ("call", t, args)
        return ("str", t)       # bare identifier = string resource name


_cache = {}


def evaluate(src, env):
    if src not in _cache:
        _cache[src] = Expr(src).parse()
    return _eval(_cache[src], env)


def _eval(n, env):
    k = n[0]
    if k == "num": return n[1]
    if k == "src": return env[n[1]]
    if k == "str": return n[1]
    if k == "call": return FUNCS[n[1]](*[_eval(a, env) for a in n[2]])
    if k == "?": return _eval(n[2], env) if _eval(n[1], env) else _eval(n[3], env)
    if k == "u-": return -_eval(n[1], env)
    if k == "u+": return _eval(n[1], env)
    if k == "u!": return not _eval(n[1], env)
    a, b = _eval(n[1], env), _eval(n[2], env)
    return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b,
            "%": lambda: math.fmod(a, b), ">": lambda: a > b, ">=": lambda: a >= b, "<": lambda: a < b,
            "<=": lambda: a <= b, "==": lambda: abs(a - b) < 1e-9 if isinstance(a, float) else a == b,
            "!=": lambda: a != b, "&&": lambda: a and b, "||": lambda: a or b}[k]()


# ============================================================================ data sources
DOW = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]
MON = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."]


def moon_phase_type(t):
    synodic = 29.530588853
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    age = ((t - ref).total_seconds() / 86400) % synodic
    return int((age / synodic) * 8 + 0.5) % 8


def environment(t, hr=72, steps=6420, goal=10000, battery=84):
    """t: aware datetime (local time)"""
    sid = t.hour * 3600 + t.minute * 60 + t.second
    return {
        "SECONDS_IN_DAY": float(sid), "MILLISECOND": t.microsecond / 1000.0,
        "SECONDS_SINCE_EPOCH": float(int(t.timestamp())),
        "HEART_RATE": float(hr), "STEP_COUNT": float(steps), "STEP_PERCENT": float(min(100, 100 * steps // goal)),
        "BATTERY_PERCENT": float(battery), "DAY_OF_WEEK_S": DOW[t.weekday()], "DAY": float(t.day),
        "MONTH_S": MON[t.month - 1], "MOON_PHASE_TYPE": float(moon_phase_type(t)),
        "IS_24_HOUR_MODE": 1.0, "HOUR_0_23_Z": f"{t.hour:02d}", "MINUTE_Z": f"{t.minute:02d}",
        "HOUR_1_12": str((t.hour - 1) % 12 + 1),
        "ACCELEROMETER_ANGLE_X": 0.0, "ACCELEROMETER_ANGLE_Y": 0.0,
        "_hhmm": t.strftime("%H:%M"),
    }


# ============================================================================ renderer
def mat(a, b, c, d, e, f):
    return np.array([[a, b, c], [d, e, f], [0, 0, 1]], float)


def T(x, y): return mat(1, 0, x, 0, 1, y)
def R(deg):
    r = math.radians(deg); c, s = math.cos(r), math.sin(r)
    return mat(c, -s, 0, s, c, 0)
def Sc(sx, sy): return mat(sx, 0, 0, 0, sy, 0)


class Renderer:
    def __init__(self, root, env, config, ambient=False):
        self.root, self.env, self.cfg, self.ambient = root, env, config, ambient
        n = CANVAS * SS
        self.prem = np.zeros((n, n, 3), np.float32)
        self.images = {}
        self.fonts = {}
        self.used_images = set()
        self.drawn = []          # (name, x, y) of named groups, for sanity checks

    # ------------------------------------------------------------- attributes
    def props(self, el, defaults):
        p = dict(defaults)
        for k, v in el.attrib.items():
            try:
                p[k] = float(v)
            except ValueError:
                p[k] = v
        for c in el:
            if c.tag == "Transform":
                p[c.get("target")] = evaluate(c.get("value"), self.env)
            if c.tag == "Variant" and self.ambient and c.get("mode") == "AMBIENT":
                p[c.get("target")] = evaluate(c.get("value"), self.env)
        return p

    def local(self, M, p):
        w, h = p.get("width", 0), p.get("height", 0)
        px, py = p.get("pivotX", 0.5) * w, p.get("pivotY", 0.5) * h
        return M @ T(p.get("x", 0), p.get("y", 0)) @ T(px, py) @ R(p.get("angle", 0)) \
            @ Sc(p.get("scaleX", 1), p.get("scaleY", 1)) @ T(-px, -py)

    # ------------------------------------------------------------- traversal
    def render(self):
        scene = self.root.find("Scene")
        self.children(scene, mat(SS, 0, 0, 0, SS, 0), 1.0)
        return self

    def children(self, el, M, alpha):
        for c in el:
            self.node(c, M, alpha)

    def node(self, el, M, alpha):
        tag = el.tag
        if tag in ("Transform", "Variant", "Gyro", "Expressions", "Image", "Reference"):
            return
        if tag == "Group":
            p = self.props(el, {})
            a = alpha * p.get("alpha", 255) / 255
            if a <= 0.001:
                return
            Ml = self.local(M, p)
            o = Ml @ np.array([p["width"] / 2, p["height"] / 2, 1])
            self.drawn.append((p["name"], o[0] / SS, o[1] / SS))
            self.children(el, Ml, a)
        elif tag == "Condition":
            exprs = {e.get("name"): e.text for e in el.find("Expressions")}
            for cmp in el.findall("Compare"):
                if evaluate(exprs[cmp.get("expression")], self.env):
                    self.children(cmp, M, alpha); return
            d = el.find("Default")
            if d is not None:
                self.children(d, M, alpha)
        elif tag in ("ListConfiguration", "BooleanConfiguration"):
            want = self.cfg[el.get("id")]
            for opt in el:
                if opt.get("id") == want:
                    self.children(opt, M, alpha)
        elif tag == "PartImage":
            self.part_image(el, M, alpha)
        elif tag == "PartDraw":
            self.part_draw(el, M, alpha)
        elif tag == "PartText":
            self.part_text(el, M, alpha)
        elif tag == "DigitalClock":
            p = self.props(el, {})
            Ml = self.local(M, p)
            for tt in el.findall("TimeText"):
                self.time_text(tt, Ml, alpha * p.get("alpha", 255) / 255)
        else:
            raise NotImplementedError(tag)

    # ------------------------------------------------------------- primitives
    def sprite(self, name):
        if name not in self.images:
            path = os.path.join(RES, "drawable-nodpi", name + ".png")
            if not os.path.exists(path):
                raise FileNotFoundError(f"missing drawable '{name}'")
            self.images[name] = Image.open(path).convert("RGBA").convert("RGBa")
        self.used_images.add(name)
        return self.images[name]

    def composite(self, layer_prem, layer_a, blend):
        if blend == "PLUS":
            self.prem += layer_prem
        else:
            self.prem = layer_prem + self.prem * (1 - layer_a[..., None])

    def part_image(self, el, M, alpha):
        p = self.props(el, {})
        a = alpha * p.get("alpha", 255) / 255
        if a <= 0.001:
            return
        img = self.sprite(el.find("Image").get("resource"))
        sw, sh = img.size
        Ml = self.local(M, p) @ Sc(p["width"] / sw, p["height"] / sh)
        inv = np.linalg.inv(Ml)
        n = CANVAS * SS
        out = img.transform((n, n), Image.AFFINE, tuple(inv[:2].flatten()), resample=Image.BICUBIC)
        arr = np.asarray(out, np.float32) / 255
        self.composite(arr[..., :3] * a, arr[..., 3] * a, p.get("blendMode"))

    def color(self, s):
        s = s.lstrip("#")
        if len(s) == 6:
            s = "FF" + s
        v = [int(s[i:i + 2], 16) / 255 for i in range(0, 8, 2)]
        return v[0], np.array(v[1:])

    def stroke_poly(self, pts, stroke, M, alpha, closed=False):
        n = CANVAS * SS
        layer = Image.new("L", (n, n), 0)
        dr = ImageDraw.Draw(layer)
        P = [(M @ np.array([x, y, 1]))[:2] for x, y in pts]
        scale = math.sqrt(abs(np.linalg.det(M[:2, :2])))
        w = max(1, int(round(float(stroke.get("thickness")) * scale)))
        if closed:
            P.append(P[0])
        dr.line([tuple(q) for q in P], fill=255, width=w, joint="curve")
        a_c, rgb = self.color(stroke.get("color"))
        m = np.asarray(layer, np.float32) / 255 * a_c * alpha
        self.composite(rgb * m[..., None], m, None)

    def part_draw(self, el, M, alpha):
        p = self.props(el, {})
        a = alpha * p.get("alpha", 255) / 255
        if a <= 0.001:
            return
        Ml = self.local(M, p)
        for sh in el:
            if sh.tag in ("Transform", "Variant"):
                continue
            q = self.props(sh, {})
            st, fi = sh.find("Stroke"), sh.find("Fill")
            if sh.tag == "Ellipse":
                cx, cy = q["x"] + q["width"] / 2, q["y"] + q["height"] / 2
                pts = [(cx + q["width"] / 2 * math.cos(t), cy + q["height"] / 2 * math.sin(t))
                       for t in np.linspace(0, 2 * math.pi, 240, endpoint=False)]
                if st is not None:
                    self.stroke_poly(pts, st, Ml, a, closed=True)
                if fi is not None:
                    n = CANVAS * SS
                    layer = Image.new("L", (n, n), 0)
                    ImageDraw.Draw(layer).polygon([tuple((Ml @ np.array([x, y, 1]))[:2]) for x, y in pts], fill=255)
                    a_c, rgb = self.color(fi.get("color"))
                    m = np.asarray(layer, np.float32) / 255 * a_c * a
                    self.composite(rgb * m[..., None], m, None)
            elif sh.tag == "Arc":
                s0, s1 = q["startAngle"], q["endAngle"]
                if abs(s1 - s0) < 1e-3:
                    continue
                ts = np.linspace(s0, s1, max(2, int(abs(s1 - s0)) + 2))
                # WFF: 0 deg = 12 o'clock, clockwise, scaled to the oval (parametric angle)
                pts = [(q["centerX"] + q["width"] / 2 * math.sin(math.radians(t)),
                        q["centerY"] - q["height"] / 2 * math.cos(math.radians(t))) for t in ts]
                self.stroke_poly(pts, st, Ml, a)
            elif sh.tag == "Line":
                self.stroke_poly([(q["startX"], q["startY"]), (q["endX"], q["endY"])], st, Ml, a)
            else:
                raise NotImplementedError(sh.tag)

    def font(self, family, size):
        key = (family, size)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(os.path.join(RES, "font", family + ".otf"), int(round(size * SS)))
        return self.fonts[key]

    def draw_text(self, s, p, M, alpha, family, size, color, align, letter=0.0):
        f = self.font(family, size)
        sp = letter * size * SS
        widths = [f.getlength(ch) for ch in s]
        tw = sum(widths) + sp * max(0, len(s) - 1)
        n = CANVAS * SS
        layer = Image.new("L", (n, n), 0)
        dr = ImageDraw.Draw(layer)
        o = M @ np.array([0, 0, 1])
        bw, bh = p["width"] * SS, p["height"] * SS
        x = o[0] + {"START": 0, "CENTER": (bw - tw) / 2, "END": bw - tw}[align]
        asc, desc = f.getmetrics()
        y = o[1] + (bh - (asc + desc)) / 2
        for ch, w in zip(s, widths):
            dr.text((x, y), ch, font=f, fill=255)
            x += w + sp
        a_c, rgb = self.color(color)
        m = np.asarray(layer, np.float32) / 255 * a_c * alpha
        self.composite(rgb * m[..., None], m, None)

    def part_text(self, el, M, alpha):
        p = self.props(el, {})
        a = alpha * p.get("alpha", 255) / 255
        if a <= 0.001:
            return
        Ml = self.local(M, p)
        t = el.find("Text")
        f = t.find("Font")
        holder = f.find("Upper") if f.find("Upper") is not None else f
        tp = holder.find("Template")
        if tp is not None:
            vals = []
            for prm in tp.findall("Parameter"):
                v = evaluate(prm.get("expression"), self.env)
                vals.append(str(int(v)) if isinstance(v, float) and v == int(v) else str(v))
            s = tp.text.replace("%%", "\x00") % tuple(vals)
            s = s.replace("\x00", "%")
        else:
            s = holder.text or ""
        if holder.tag == "Upper":
            s = s.upper()
        self.draw_text(s, p, Ml, a, f.get("family"), float(f.get("size")), f.get("color"),
                       t.get("align", "CENTER"), float(f.get("letterSpacing", 0)))

    def time_text(self, el, M, alpha):
        p = self.props(el, {})
        a = alpha * p.get("alpha", 255) / 255
        if a <= 0.001:
            return
        f = el.find("Font")
        self.draw_text(self.env["_hhmm"], p, self.local(M, p), a, f.get("family"), float(f.get("size")),
                       f.get("color"), el.get("align", "CENTER"))

    # ------------------------------------------------------------- output
    def image(self, full=False):
        n = CANVAS * SS
        img = np.clip(self.prem, 0, 1)
        yy, xx = np.mgrid[0:n, 0:n]
        d = np.hypot(xx - n / 2 + 0.5, yy - n / 2 + 0.5)
        mask = np.clip(n / 2 - d, 0, 1)[..., None]
        out = img * mask + np.array([1.0, 1.0, 1.0]) * (1 - mask)
        im = Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB")
        return im if full else im.resize((CANVAS, CANVAS), Image.LANCZOS)


def render(t, cfg=None, ambient=False, **env_kw):
    cfg = cfg or dict(modus="uhrwerk", komet="TRUE")
    root = ET.parse(XML).getroot()
    r = Renderer(root, environment(t, **env_kw), cfg, ambient).render()
    return r


TZ = dt.timezone(dt.timedelta(hours=1))


def memory_report(names):
    tot = 0
    for n in names:
        w, h = Image.open(os.path.join(RES, "drawable-nodpi", n + ".png")).size
        tot += w * h * 4
    return tot


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    t0 = dt.datetime(2026, 11, 8, 22, 59, 30, tzinfo=TZ)
    if cmd == "preview":
        r = render(t0)
        r.image().save(os.path.join(RES, "drawable-nodpi", "preview.png"))
        print("preview written")
    elif cmd == "gallery":
        out = os.path.join(ROOT, "build", "sim")
        os.makedirs(out, exist_ok=True)
        render(t0).image(full=True).save(os.path.join(out, "aktiv.png"))
        render(t0, ambient=True).image(full=True).save(os.path.join(out, "ambient.png"))
        render(t0, cfg=dict(modus="echt", komet="TRUE")).image(full=True).save(os.path.join(out, "echt.png"))
        render(t0, cfg=dict(modus="uhrwerk", komet="FALSE")).image(full=True).save(os.path.join(out, "ohne_komet.png"))
        frames = []
        for i in range(64):                      # 2 s steps -> Mercury does one orbit
            frames.append(render(t0 + dt.timedelta(seconds=2 * i, milliseconds=130 * i)).image())
        frames[0].save(os.path.join(out, "animation.gif"), save_all=True, append_images=frames[1:],
                       duration=80, loop=0)
        print("gallery written to", out)
