"""
Single source of truth for the solar-system watch face.

Geometry, orbital data and the WFF expression builders live here and are
shared by render_assets.py (sprites), gen_watchface.py (watchface.xml) and
simulate.py (offline preview renderer).

Coordinate conventions
----------------------
* Canvas: 450 x 450 virtual pixels (WFF <WatchFace width/height>).
* The orbital plane is seen from ELEV degrees above the ecliptic (north side).
  World coords: X to the right, Z away from the viewer (far side = up on screen).
* Screen longitude lambda (deg) is measured counter-clockwise from screen right.
  The planets move clockwise on screen (lambda decreases), like in the reference image.
      screen x = SUN_X + r * cos(lambda)
      screen y = SUN_Y - r * K * sin(lambda)        K = sin(ELEV)
* WFF angles (rotation, Arc start/end) are degrees clockwise from 12 o'clock.
  For a point on an orbit the corresponding WFF angle is  a = 90 - lambda.
"""
import math

CANVAS = 450
FACE_C = CANVAS / 2            # centre of the round display
SUN_X, SUN_Y = 225.0, 262.0     # sun position (below centre, room for time + date)
ELEV = 30.0                     # viewing elevation in degrees
K = math.sin(math.radians(ELEV))
COS_E = math.cos(math.radians(ELEV))
DEPTH_GAIN = 0.16               # perspective size cue: near planets up to +16 %, far ones -16 %
N_FRAMES = 24                   # pre-rendered lighting frames per planet (every 15 deg)
SUN_R = 22.0                    # photosphere radius (display px)
BELT_R = 105.0                  # asteroid belt radius
ORBIT_GLOW = 0.07               # brightness of the static orbit lines
BATTERY_R = 200.0               # battery arc radius (around the face centre)
BATTERY_A0, BATTERY_A1 = 155.0, 205.0   # WFF angles of the battery arc (bottom)

# ---------------------------------------------------------------------------
# Time sources
# ---------------------------------------------------------------------------
# continuous seconds of the day (ms resolution) - used for the fast planets
T_SMOOTH = "([SECONDS_IN_DAY] + [MILLISECOND] / 1000)"
T_COARSE = "[SECONDS_IN_DAY]"
# days since J2000.0 (2000-01-01 12:00 TT ~ UTC), for the "real positions" mode
D_J2000 = "([SECONDS_SINCE_EPOCH] / 86400 - 10957.5)"

# ---------------------------------------------------------------------------
# Planets
# ---------------------------------------------------------------------------
# key, German name, orbit radius (px), body radius (px), sprite margin,
# orbits per day in clock mode, mean longitude J2000 (deg), sidereal period (days),
# needs a copy behind the sun (inner orbits can pass behind the sun disc)
#
# Clock mode: Neptune = exactly 1 orbit / 24 h. The others are scaled with the real
# period ratios and rounded to whole orbits per day so nothing jumps at midnight:
#   real ratio   ->  used
#   Mercury 684.6 -> 685   (2 min 6 s per orbit)
#   Venus   267.9 -> 268   (5 min 22 s)
#   Earth   164.8 -> 165   (8 min 44 s)
#   Mars     87.6 ->  88   (16 min 22 s)
#   Jupiter  13.9 ->  14   (1 h 43 min)
#   Saturn    5.6 ->   6   (4 h)       <- largest rounding error (7 %)
#   Uranus    1.96 ->  2   (12 h)
#   Neptune   1    ->  1   (24 h)
PLANETS = [
    dict(key="merkur",  name="Merkur",  r=36,  R=5.0,  m=1.45, n=685, L0=252.25, P=87.969,   behind=True),
    dict(key="venus",   name="Venus",   r=51,  R=6.5,  m=1.50, n=268, L0=181.98, P=224.701,  behind=True),
    dict(key="erde",    name="Erde",    r=68,  R=7.0,  m=1.50, n=165, L0=100.46, P=365.256,  behind=False),
    dict(key="mars",    name="Mars",    r=86,  R=5.5,  m=1.50, n=88,  L0=355.43, P=686.98,   behind=False),
    dict(key="jupiter", name="Jupiter", r=124, R=14.0, m=1.15, n=14,  L0=34.40,  P=4332.59,  behind=False),
    dict(key="saturn",  name="Saturn",  r=151, R=10.5, m=2.40, n=6,   L0=49.94,  P=10759.22, behind=False),
    dict(key="uranus",  name="Uranus",  r=174, R=8.5,  m=1.45, n=2,   L0=313.23, P=30688.5,  behind=False),
    dict(key="neptun",  name="Neptun",  r=194, R=8.0,  m=1.45, n=1,   L0=304.88, P=60182.0,  behind=False),
]
# Arrangement of the approved reference image at 22:59:30 (screen longitudes, deg).
# Clock mode is phased so that the watch shows exactly this picture at that time.
PREVIEW_T = 22 * 3600 + 59 * 60 + 30
PREVIEW_LAM = dict(merkur=332, venus=78, erde=150, mars=28, jupiter=212, saturn=32, uranus=245, neptun=348,
                   mond=10, io=20, europa=200, ganymed=320, kallisto=150)
# eccentricity and longitude of perihelion (J2000) for the equation of centre in real mode
ORBIT_EL = dict(merkur=(0.20563, 77.46), venus=(0.00677, 131.53), erde=(0.01671, 102.94),
                mars=(0.09340, 336.04), jupiter=(0.04839, 14.75), saturn=(0.05386, 92.43),
                uranus=(0.04726, 170.96), neptun=(0.00859, 44.97))


# Earth's Moon (relative to Earth, in the orbital plane)
MOON = dict(r=14.0, R=2.3, n_clock=2206, L0_real=218.316, rate_real=13.176396)
# Galilean moons (relative to Jupiter). Clock mode keeps the 1:2:4 Laplace resonance.
GALILEAN = [
    dict(key="io",       r=19.0, R=1.4, n_clock=4320, L0=106.1, P=1.769),
    dict(key="europa",   r=24.0, R=1.3, n_clock=2160, L0=175.7, P=3.551),
    dict(key="ganymed",  r=30.0, R=1.8, n_clock=1080, L0=120.6, P=7.155),
    dict(key="kallisto", r=38.0, R=1.7, n_clock=463,  L0=84.5,  P=16.689),
]

# Static comet (head position in canvas px, tail points away from the sun)
COMET_HEAD = (SUN_X + 113, SUN_Y - 84)     # upper right, tail towards the rim

# Look
GOLD = "#DCBE87"
GOLD_DIM = "#8A7650"
TEXT = "#F0ECE4"
TEXT_DIM = "#C8C4BC"
CYAN = "#96D7F0"

MODES = ("uhrwerk", "echt")


def fmt(v):
    """number -> compact string for XML"""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.5f}".rstrip("0").rstrip(".")


def clock_phase(key, n):
    """start angle so that the body sits at PREVIEW_LAM[key] at PREVIEW_T"""
    f0 = (n * PREVIEW_T / 86400) % 1
    return (PREVIEW_LAM[key] + 360 * f0) % 360


def clock_lam(key, n, t):
    # clockwise (screen longitude decreases), always positive for the frame index
    return f"({fmt(round(clock_phase(key, n), 4))} + 360 - 360 * fract({n} * {t} / 86400))"


def lam_expr(p, mode):
    """screen longitude of planet p in degrees (WFF expression)"""
    if mode == "uhrwerk":
        return clock_lam(p["key"], p["n"], T_SMOOTH if p["n"] >= 14 else T_COARSE)
    L0 = p["L0"]
    e, peri = ORBIT_EL[p["key"]]
    L = f"({fmt(L0)} + 360 * fract({D_J2000} / {fmt(p['P'])}))"
    M = f"rad({L} - {fmt(peri)})"
    # true longitude ~ mean longitude + equation of centre (2e sin M + 5/4 e^2 sin 2M)
    # seen from below the ecliptic (mirror) so the planets turn clockwise as in clock mode
    return f"(720 - ({L} + deg({fmt(2 * e)} * sin({M}) + {fmt(1.25 * e * e)} * sin(2 * {M}))))"


def moon_expr(mode):
    if mode == "uhrwerk":
        return clock_lam("mond", MOON["n_clock"], T_SMOOTH)
    return f"(720 - ({fmt(MOON['L0_real'])} + 360 * fract({fmt(MOON['rate_real'] / 360)} * {D_J2000})))"


def galilean_expr(g, mode):
    if mode == "uhrwerk":
        return clock_lam(g["key"], g["n_clock"], T_SMOOTH)
    return f"(720 - ({fmt(g['L0'])} + 360 * fract({D_J2000} / {fmt(g['P'])})))"


def sx_expr(lam, r, cx=SUN_X):
    return f"{fmt(cx)} + {fmt(r)} * cos(rad({lam}))"


def sy_expr(lam, r, cy=SUN_Y):
    return f"{fmt(cy)} - {fmt(r * K)} * sin(rad({lam}))"


def depth_scale_expr(lam, r):
    # near side (sin < 0) -> bigger
    g = DEPTH_GAIN * COS_E * r / 194.0
    return f"(1 - {fmt(g)} * sin(rad({lam})))"


def frame_index_expr(lam):
    step = 360 / N_FRAMES
    return f"(floor(({lam} % 360 + {fmt(step / 2)}) / {fmt(step)}) % {N_FRAMES})"


def far_expr(lam):
    """true when the body is on the far side (behind the sun / its planet)"""
    return f"sin(rad({lam})) > 0"


def near_expr(lam):
    return f"sin(rad(0 - {lam})) >= 0"


def light_dir(lam_deg):
    """direction from a body at orbital longitude lam towards the sun, in screen space
    (x right, y down, z towards the viewer)"""
    l = math.radians(lam_deg)
    Xw, Zw = math.cos(l), math.sin(l)
    L = (-Xw, 0.0, -Zw)
    r_ = (1, 0, 0)
    u_ = (0, COS_E, K)
    f_ = (0, -K, COS_E)
    dot = lambda a, b: sum(i * j for i, j in zip(a, b))
    v = (dot(L, r_), -dot(L, u_), -dot(L, f_))
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def sprite_size(p):
    """display size (px) of a planet sprite (square)"""
    return int(math.ceil(2 * p["R"] * p["m"])) | 1  # odd -> exact centre


SPRITE_SCALE = 2   # sprite files are rendered at 2x display size (crisp after depth scaling)

# ---- sprite geometry shared by renderer / generator / simulator -------------
SUN_OVERLAY = 60        # crop of the background around the sun, drawn over planets behind it
MOONPHASE_ICON = 13


def small_sprite(R):
    return int(math.ceil(2 * R * 1.4)) | 1
