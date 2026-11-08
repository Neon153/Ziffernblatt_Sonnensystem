"""
The look of the approved reference render (sonnensystem_zifferblatt_v4.png), as a module.

Everything here works at REF = 900 px for the whole face (= 2x the 450 px WFF canvas).
render_background()  -> the static layer: stars, nebula, orbit lines, asteroid belt, sun with
                        corona / glow / bloom / rings, comet, bezel ticks, battery track
planet_sprite()      -> one planet lit from a given direction, finished exactly like the
                        reference (ACES filmic tonemap + gamma), as straight-alpha RGBA
"""
import math

import numpy as np

from config import K, COS_E, SUN_X, SUN_Y, SUN_R, CANVAS, BELT_R, ORBIT_GLOW, BATTERY_R, BATTERY_A0, BATTERY_A1

REF = 900
F = REF / CANVAS             # 2.0
C = REF / 2
CY = SUN_Y * F               # 488
R_FACE = 440
GOLD = np.array([0.86, 0.74, 0.52])


# ----------------------------------------------------------------------------- helpers
def vnoise(u, v, octaves=5, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros_like(u, dtype=np.float32)
    amp, freq = 1.0, 1.0
    for _ in range(octaves):
        g = r.random((64, 64)).astype(np.float32)
        x = (u * freq) % 64; y = (v * freq) % 64
        x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int)
        fx = x - x0; fy = y - y0
        fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy)
        x1 = (x0 + 1) % 64; y1 = (y0 + 1) % 64
        a = g[y0, x0] * (1 - fx) + g[y0, x1] * fx
        b = g[y1, x0] * (1 - fx) + g[y1, x1] * fx
        out += amp * (a * (1 - fy) + b * fy)
        amp *= 0.5; freq *= 2
    return out / 1.9375


def warp(u, v, seed, amt=0.25, sc=3):
    return (u + amt * (vnoise(u * sc + 7, v * sc + 1, 3, seed) - 0.5),
            v + amt * (vnoise(u * sc + 3, v * sc + 9, 3, seed + 1) - 0.5))


def aces(x):
    x = np.maximum(x, 0) * 0.9
    return (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)


def display(lin):
    """linear scene value -> final pixel value, exactly like the reference"""
    return np.clip(aces(lin), 0, 1) ** (1 / 1.05)


def splat(buf, xs, ys, vals, col):
    S = buf.shape[0]
    x0 = np.floor(xs).astype(int); y0 = np.floor(ys).astype(int)
    fx = xs - x0; fy = ys - y0
    for ox, oy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi = np.clip(x0 + ox, 0, S - 1); yi = np.clip(y0 + oy, 0, S - 1)
        np.add.at(buf, (yi, xi), (vals * w)[:, None] * col)


def to_screen(r_ref, lam_deg):
    """orbit radius (ref px) + screen longitude -> ref x, y, depth (far = positive)"""
    l = np.radians(lam_deg)
    X, Z = r_ref * np.cos(l), r_ref * np.sin(l)
    return C + X, CY - Z * K, Z * COS_E


# ----------------------------------------------------------------------------- surfaces
def solid(c, n=0.0, seed=1, scale=4):
    def f(u, v):
        if not n:
            return np.broadcast_to(np.array(c, np.float32), u.shape + (3,)).copy()
        nz = vnoise(u * scale + 10, v * scale + 10, 4, seed)
        return np.array(c)[None, None, :] * (1 - n + n * 1.6 * nz)[..., None]
    return f


def banded(cols, seed, freq=7, turb=0.08):
    cols = np.array(cols)
    def f(u, v):
        nz = vnoise(u * 6 + 3, v * 6 + 3, 4, seed)
        t = (v + turb * (nz - 0.5) * 2) * freq
        k = (np.sin(t * np.pi) * 0.5 + 0.5) * (len(cols) - 1)
        i = np.clip(np.floor(k).astype(int), 0, len(cols) - 2); fr = (k - i)[..., None]
        return cols[i] * (1 - fr) + cols[i + 1] * fr
    return f


def earth_land(u, v):
    wu, wv = warp(u, v, 61, 0.4, 2)
    return vnoise(wu * 3 + 5, wv * 3 + 9, 6, 11)


def earth_spec(u, v):
    return (earth_land(u, v) <= 0.53).astype(np.float32) * 0.8


def earth_night(u, v):
    nz = earth_land(u, v)
    coast = np.clip(1 - np.abs(nz - 0.56) * 12, 0, 1)
    sparkle = (vnoise(u * 40, v * 40, 2, 71) > 0.62).astype(np.float32)
    return (nz > 0.53) * (0.25 * coast + 0.6 * sparkle * (nz < 0.62)) * 0.9


def earth(u, v):
    nz = earth_land(u, v)
    ocean = np.array([0.03, 0.12, 0.32]); green = np.array([0.18, 0.36, 0.14]); desert = np.array([0.55, 0.45, 0.28])
    c = np.where((nz > 0.53)[..., None], np.where((nz > 0.62)[..., None], desert, green), ocean)
    cu, cv = warp(u, v, 81, 0.5, 3)
    clouds = np.clip((vnoise(cu * 5 + 1, cv * 5 + 2, 6, 21) - 0.48) * 3.2, 0, 1) ** 1.3
    ice = np.clip((np.abs(v) - 0.82) * 8, 0, 1)
    c = c * (1 - clouds[..., None]) + clouds[..., None] * 0.95
    return c * (1 - ice[..., None]) + ice[..., None] * 0.95


def mars(u, v):
    wu, wv = warp(u, v, 91, 0.3, 3)
    nz = vnoise(wu * 4 + 2, wv * 4 + 2, 6, 6)
    base = np.array([0.74, 0.36, 0.17]) * (0.75 + 0.5 * nz)[..., None]
    dark = np.clip((vnoise(wu * 2, wv * 2, 4, 66) - 0.55) * 4, 0, 1)
    base = base * (1 - 0.45 * dark[..., None])
    cap = np.clip((v + 0.86) * -10, 0, 1) + np.clip((v - 0.9) * 10, 0, 1)
    return base * (1 - cap[..., None]) + cap[..., None] * 0.92


def mercury(u, v):
    nz = vnoise(u * 5, v * 5, 6, 4)
    craters = np.zeros_like(u)
    r_ = np.random.default_rng(12)
    for _ in range(14):
        cx_, cy_, cr = r_.uniform(-0.8, 0.8), r_.uniform(-0.8, 0.8), r_.uniform(0.06, 0.2)
        dd = np.hypot(u - cx_, v - cy_) / cr
        craters += np.where(dd < 1, -0.25 * (1 - dd), 0) + np.exp(-((dd - 1) ** 2) / 0.02) * 0.15
    return np.array([0.56, 0.53, 0.5]) * (0.7 + 0.5 * nz + craters)[..., None]


def jupiter(u, v):
    u, v = warp(u, v, 33, 0.07, 4)
    c = banded([[0.85, 0.75, 0.62], [0.62, 0.45, 0.32], [0.92, 0.86, 0.76], [0.70, 0.52, 0.38]], 31, freq=6, turb=0.12)(u, v)
    spot = np.exp(-(((u - 0.3) / 0.16) ** 2 + ((v - 0.35) / 0.09) ** 2))
    return c * (1 - spot[..., None]) + spot[..., None] * np.array([0.72, 0.32, 0.2])


SURF = dict(
    merkur=dict(fn=mercury),
    venus=dict(fn=solid([0.92, 0.80, 0.55], 0.15, 5, 3), atmo=[0.9, 0.8, 0.5]),
    erde=dict(fn=earth, atmo=[0.35, 0.6, 1.0], night=earth_night, spec=earth_spec),
    mars=dict(fn=mars, atmo=[0.8, 0.5, 0.35]),
    jupiter=dict(fn=jupiter),
    saturn=dict(fn=banded([[0.90, 0.80, 0.58], [0.78, 0.66, 0.45], [0.93, 0.85, 0.66]], 41, freq=5, turb=0.05),
                rings=(1.25, 2.3, [0.85, 0.77, 0.6])),
    uranus=dict(fn=solid([0.62, 0.86, 0.90], 0.06, 7, 2), atmo=[0.6, 0.9, 1.0]),
    neptun=dict(fn=banded([[0.22, 0.38, 0.85], [0.18, 0.30, 0.75], [0.28, 0.45, 0.92]], 51, freq=4, turb=0.15),
                atmo=[0.4, 0.55, 1.0]),
    mond=dict(fn=solid([0.62, 0.62, 0.6], 0.3, 8, 4)),
    io=dict(fn=solid([0.85, 0.7, 0.35], 0.2, 9, 3)),
    europa=dict(fn=solid([0.9, 0.9, 0.85], 0.2, 10, 3)),
    ganymed=dict(fn=solid([0.7, 0.62, 0.55], 0.2, 11, 3)),
    kallisto=dict(fn=solid([0.55, 0.5, 0.45], 0.2, 12, 3)),
)


# ----------------------------------------------------------------------------- planet sprite
def planet_sprite(n_px, rad, key, L, vignette=1.0, ss=4):
    """n_px: sprite size in ref px, rad: body radius in ref px. Returns straight RGBA float (n, n, 4)."""
    s = SURF[key]
    fn, atmo, rings, night, spec = s["fn"], s.get("atmo"), s.get("rings"), s.get("night"), s.get("spec")
    n = n_px * ss
    c = (n - 1) / 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    X, Y = (xx - c) / ss, (yy - c) / ss                    # ref px units
    d = np.hypot(X, Y)
    L = np.array(L, np.float32)
    prem = np.zeros((n, n, 3), np.float32)
    alpha = np.zeros((n, n), np.float32)

    def over(col, a):
        nonlocal prem, alpha
        prem = col * a[..., None] + prem * (1 - a[..., None])
        alpha = a + alpha * (1 - a)

    def ring_layer(front):
        inner, outer, col = rings
        rr = np.hypot(X, Y / K)
        mask = (rr > inner * rad) & (rr < outer * rad)
        mask &= (Y > 0) if front else (Y <= 0)
        if not front:
            mask &= d > rad
        t = (rr - inner * rad) / ((outer - inner) * rad)
        dens = 0.55 + 0.25 * np.sin(t * 9) + 0.12 * np.sin(t * 23) + 0.08 * np.sin(t * 61)
        dens *= np.where(t < 0.18, 0.35, 1.0)
        dens *= np.where((t > 0.62) & (t < 0.68), 0.12, 1.0)
        Lp = np.array([L[0], L[1] / K]); Lp /= np.linalg.norm(Lp) + 1e-9
        Yr = Y / K
        proj = X * Lp[0] + Yr * Lp[1]; perp = np.abs(-X * Lp[1] + Yr * Lp[0])
        shadow = np.where((proj < 0) & (perp < rad), 0.12, 1.0)
        colr = np.array(col)[None, None, :] * (dens * shadow)[..., None]
        a = np.clip(dens * (0.75 if front else 0.9), 0, 1) * mask
        over(colr, a)

    if rings:
        ring_layer(False)
    z = np.sqrt(np.clip(rad ** 2 - X ** 2 - Y ** 2, 0, None))
    N = np.stack([X, Y, z], -1) / rad
    ndl = np.clip(N @ L, 0, 1)
    shade = ndl ** 0.9 + 0.05
    back = np.clip(-L[2], 0, 1) * (1 - N[..., 2]) ** 4 * 0.6
    col = fn(X / rad, Y / rad) * shade[..., None] + back[..., None] * np.array([1.0, 0.75, 0.45])
    if spec is not None:
        H = L + np.array([0, 0, 1.0], np.float32); H /= np.linalg.norm(H)
        sp = np.clip(N @ H, 0, 1) ** 40 * spec(X / rad, Y / rad) * (ndl > 0)
        col += sp[..., None] * np.array([1.0, 0.9, 0.75]) * 0.9
    if night is not None:
        dark = np.clip(-(N @ L) * 3, 0, 1)
        col += (night(X / rad, Y / rad) * dark)[..., None] * np.array([1.0, 0.72, 0.35])
    if atmo is not None:
        rim = (1 - N[..., 2]) ** 3
        term = np.clip(N @ L + 0.25, 0, 1)
        col += np.array(atmo)[None, None, :] * (rim * term)[..., None] * 0.9
    over(col, np.clip(rad - d + 0.5, 0, 1))
    if rings:
        ring_layer(True)
    if atmo is not None:                                   # additive halo -> light with alpha
        halo = np.exp(-np.clip(d - rad, 0, None) / 2.0) * (d >= rad)
        hl = np.clip((X * L[0] + Y * L[1]) / (d + 1e-6) + 0.3, 0, 1)
        h = np.clip(halo * hl * 0.35, 0, 1)
        prem = prem + np.array(atmo) * h[..., None]
        alpha = alpha + h * (1 - alpha)

    # box filter down
    prem = prem.reshape(n_px, ss, n_px, ss, 3).mean(axis=(1, 3))
    alpha = alpha.reshape(n_px, ss, n_px, ss).mean(axis=(1, 3))
    lin = np.where(alpha[..., None] > 1e-4, prem / np.maximum(alpha[..., None], 1e-4), 0)
    rgb = display(lin * vignette)
    return np.dstack([rgb, np.clip(alpha, 0, 1)])


def vignette_at(dist_ref):
    return 1 - 0.45 * (dist_ref / R_FACE) ** 3


# ----------------------------------------------------------------------------- background
def render_background(orbits_ref, comet=None, ticks=True, battery_track=True):
    """returns the final display image (REF, REF, 3) of the static layer"""
    S = REF
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    dx, dy = xx - C, yy - C
    dist = np.hypot(dx, dy)
    theta = np.arctan2(dx, -dy) % (2 * np.pi)
    img = np.zeros((S, S, 3), np.float32)

    # stars (same random sequence as the reference)
    temps = [np.array([0.75, 0.85, 1.0]), np.array([1, 1, 1.0]), np.array([1.0, 0.93, 0.8]), np.array([1.0, 0.8, 0.6])]
    for _ in range(320):
        x, y = rng.uniform(0, S, 2)
        b = rng.uniform(0.1, 1.0) ** 3.0
        tint = temps[rng.choice(4, p=[0.2, 0.45, 0.25, 0.1])]
        s = 0.5 + b * 0.8
        x0, x1 = int(max(0, x - 8)), int(min(S, x + 9)); y0, y1 = int(max(0, y - 8)), int(min(S, y + 9))
        m = np.exp(-((xx[y0:y1, x0:x1] - x) ** 2 + (yy[y0:y1, x0:x1] - y) ** 2) / (2 * s * s))
        img[y0:y1, x0:x1] += m[..., None] * tint * b
    neb = vnoise(xx / 90, yy / 90, 4, 99)
    band = np.exp(-((dx * 0.55 + dy * 0.83 + 120) ** 2) / (2 * 120 ** 2))
    img += (band * np.clip(neb - 0.35, 0, 1))[..., None] * np.array([0.10, 0.06, 0.14])

    # orbit lines (base brightness only, the bright trails are drawn live on the watch)
    orb = np.zeros_like(img)
    for i, r in enumerate(orbits_ref):
        n = int(r * 30)
        lam = np.linspace(0, 360, n, endpoint=False)
        x, y, depth = to_screen(r, lam)
        col = np.array([0.45, 0.85, 1.0]) if i == 2 else 0.6 * GOLD + 0.4
        near = 0.6 + 0.4 * (-depth / r * 0.5 + 0.5)
        splat(orb, x, y, ORBIT_GLOW * near * (2 * np.pi * r / n) * 0.9, col)
    img += orb

    # asteroid belt
    nb = 2600
    br = rng.normal(BELT_R * F, 9, nb); bl = rng.uniform(0, 360, nb)
    bx, by, _ = to_screen(br, bl)
    bb = rng.uniform(0.05, 0.35, nb) ** 1.5
    splat(img, bx, by, bb, np.array([0.9, 0.82, 0.7]))

    # sun
    R_SUN = SUN_R * F
    q = R_SUN / 34                                         # size relative to the reference sun
    sdx, sdy = xx - C, yy - CY
    sd = np.hypot(sdx, sdy)
    ang = np.arctan2(sdy, sdx)
    stream = 0.6 + 0.8 * vnoise(np.cos(ang) * 6 + 20, np.sin(ang) * 6 + 20, 3, 77)
    glow = (1.1 * np.exp(-np.clip(sd - R_SUN, 0, None) / (9 * q)) +
            0.55 * stream * np.exp(-np.clip(sd - R_SUN, 0, None) / (34 * q ** 0.5)) + 0.14 * np.exp(-sd / 130))
    img += glow[..., None] * np.array([1.0, 0.58, 0.2])
    for rr, a in ((62 * q, 0.10), (96 * q, 0.05)):                # static light rings around the sun
        img += (np.exp(-((sd - rr) ** 2) / (2 * (1.6 * q) ** 2)) * a)[..., None] * np.array([1.0, 0.5, 0.25])
    pa = np.deg2rad(-35)
    pcx, pcy = C + (R_SUN + 2 * q) * np.cos(pa), CY + (R_SUN + 2 * q) * np.sin(pa)
    pd = np.hypot(xx - pcx, yy - pcy)
    loop = np.exp(-((pd - 9 * q) ** 2) / (2 * (1.8 * q) ** 2)) * (sd > R_SUN)
    loop *= 0.7 + 0.6 * vnoise(xx / 2, yy / 2, 3, 5)
    img += loop[..., None] * np.array([1.6, 0.45, 0.15])
    mu = np.sqrt(np.clip(1 - (sd / R_SUN) ** 2, 0, 1))
    limb = 0.35 + 0.65 * mu ** 0.6
    gran = vnoise(xx / (2.6 * q), yy / (2.6 * q), 4, 3)
    spots = np.exp(-(((sdx + 9 * q) ** 2 + (sdy - 6 * q) ** 2) / (6 * q * q))) + 0.7 * np.exp(-(((sdx - 12 * q) ** 2 + (sdy + 4 * q) ** 2) / (3 * q * q)))
    sun_col = np.stack([np.ones_like(mu), 0.62 + 0.3 * mu, 0.18 + 0.45 * mu ** 2], -1)
    sun = sun_col * (limb * (0.85 + 0.3 * gran) * (1 - 0.6 * spots))[..., None] * 0.8
    aa = np.clip(R_SUN - sd + 0.5, 0, 1)[..., None]
    img[:] = img * (1 - aa) + np.maximum(img, sun) * aa

    if comet is not None:                                  # static comet, tail away from the sun
        cx, cy = comet
        v = np.array([cx - C, cy - CY]); v /= np.linalg.norm(v)
        nrm = np.array([-v[1], v[0]])
        px, py = xx - cx, yy - cy
        along = px * v[0] + py * v[1]; across = px * nrm[0] + py * nrm[1]
        t = np.clip(along / 150, 0, 1)
        ion = (along > 0) * np.exp(-(across ** 2) / (2 * (1 + 7 * t) ** 2)) * np.exp(-along / 70)
        across2 = across - 0.0025 * along ** 2
        dust = (along > 0) * np.exp(-(across2 ** 2) / (2 * (2 + 14 * t) ** 2)) * np.exp(-along / 55)
        head = np.exp(-(px ** 2 + py ** 2) / (2 * 1.6 ** 2)) * 2.5 + np.exp(-(px ** 2 + py ** 2) / (2 * 5 ** 2)) * 0.5
        img += ion[..., None] * np.array([0.35, 0.6, 1.0]) * 0.9
        img += dust[..., None] * np.array([1.0, 0.85, 0.6]) * 0.6
        img += head[..., None] * np.array([0.8, 0.95, 1.0])

    if ticks:
        fr = theta / (2 * np.pi) * 60
        off = np.abs(fr - np.round(fr)) * (2 * np.pi * dist / 60)
        minor = (off < 0.7) & (dist > 412) & (dist < 422)
        hr = np.abs(theta / (2 * np.pi) * 12 - np.round(theta / (2 * np.pi) * 12)) * (2 * np.pi * dist / 12)
        major = (hr < 1.3) & (dist > 404) & (dist < 425)
        img += (minor * 0.35 + major * 0.9)[..., None] * GOLD
    if battery_track:
        a0, a1 = np.deg2rad(BATTERY_A0), np.deg2rad(BATTERY_A1)
        arc = np.exp(-((dist - BATTERY_R * F) ** 2) / (2 * 1.2 ** 2)) * ((theta > a0) & (theta < a1))
        img += (arc * 0.12)[..., None] * GOLD

    img *= (1 - 0.45 * (dist / R_FACE) ** 3)[..., None]
    from scipy.ndimage import gaussian_filter
    bright = np.clip(img - 1.4, 0, None)
    img = img + sum(gaussian_filter(bright, sigma=(sg, sg, 0)) * w for sg, w in ((3, 0.35), (10, 0.22), (30, 0.15)))
    out = display(img)
    mask = np.clip(R_FACE - dist + 0.5, 0, 1)[..., None]
    return out * mask + np.array([0.05, 0.05, 0.055]) * (1 - mask)


def trail_profile(earth=False):
    """display brightness of a trail line at its centre as a function of the angle behind the
    planet (deg), measured exactly like the reference splat: returns (base, f(behind_deg))"""
    def peak(I):
        # line energy per px length = I * 0.9 * near(0.8); bilinear splat peak ~ 0.75 of it
        return float(display(np.array(I * 0.9 * 0.8 * 0.75)))
    base = peak(0.05)
    if earth:
        return base, lambda b, p: peak(0.05 + 0.5 * (b < 360 * p) * (0.35 + 0.65 * math.exp(-math.radians(b) / 2.5)))
    return base, lambda b: peak(0.05 + 0.32 * math.exp(-math.radians(b) / 0.8))
