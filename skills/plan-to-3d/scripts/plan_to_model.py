#!/usr/bin/env python3
"""
Stage 2 - plan_to_model.py
Turn extracted drawing primitives into a measured 3D building model.

The rule this stage obeys: every solid it emits is traced from something that is
actually drawn on the sheet.  It does not invent a room, a wall or an area, and
it does not drop one.  Areas are reported from the drawing's own hatch geometry,
not from the rasterised approximation used for the 3D shell.

    python plan_to_model.py <extract-dir> --out model.json [--res 20]

Per drawing frame (= one plan on the sheet):
  1. area zones   solid hatches -> exact m2 per hatch colour, kept separate
  2. floor plate  union of the zones with interior holes closed
  3. walls        (a) double-line pairs in the vector linework
                  (b) thin free-space bands between drawn lines
                  (c) the exterior ring implied by the gross-area outline
  4. openings     door swings (arcs) and glazing (tight parallel line pairs)
  5. spaces       plate minus walls, split into connected spaces
Solids are emitted as axis-aligned boxes obtained by greedy rectangle
decomposition of each mask - exact to the raster, and trivial to render.
"""
import argparse, collections, json, math, os, pickle, re, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

WALL_H   = 2.70          # m, finished ceiling height  (--height)
SILL     = 0.90          # m, window sill
HEAD     = 2.20          # m, window / door head
SLAB     = 0.25          # m, structural slab shown under each floor


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def tri_area(p):
    (x1, y1), (x2, y2), (x3, y3) = p[:3]
    return abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0


def greedy_rects(mask):
    """Decompose a binary mask into few axis-aligned rectangles (i0,j0,i1,j1)."""
    m = mask.copy()
    H, W = m.shape
    rects = []
    rows = np.flatnonzero(m.any(axis=1))
    for i in rows:
        if not m[i].any():
            continue
        j = 0
        row = m[i]
        while j < W:
            if not row[j]:
                j += 1; continue
            k = j
            while k < W and row[k]:
                k += 1
            # extend the run downwards while the same columns stay set
            i2 = i + 1
            while i2 < H and m[i2, j:k].all():
                i2 += 1
            m[i:i2, j:k] = False
            rects.append((i, j, i2, k))
            row = m[i]
            j = k
    return rects


class Sheet:
    def __init__(self, geom, glyphs, unit_mm, res_mm):
        self.geom, self.glyphs = geom, glyphs
        self.unit_mm, self.res_mm = unit_mm, res_mm
        self.upx = res_mm / unit_mm          # drawing units per pixel
        self.m_per_px = res_mm / 1000.0

    # -- colour roles --------------------------------------------------------
    def color_stats(self):
        """Area / count / drawn-length per colour.

        Solid fills reach the package as triangle fans: every triangle turns up
        once open (3 points) and once closed (4 points), so both forms are read
        as fill and only genuine polylines are measured as line work."""
        fa, fn, ll = (collections.Counter() for _ in range(3))
        s2 = (self.unit_mm / 1000.0) ** 2
        for col, polys in self.geom:
            for pl in polys:
                if len(pl) == 3:
                    fa[col] += tri_area(pl) * s2
                    fn[col] += 1
                elif len(pl) == 4 and pl[0] == pl[3]:
                    continue                       # the closed twin of a triangle
                else:
                    for i in range(len(pl) - 1):
                        ll[col] += math.hypot(pl[i + 1][0] - pl[i][0],
                                              pl[i + 1][1] - pl[i][1]) * self.unit_mm / 1000.
        return fa, fn, ll

    # -- frames --------------------------------------------------------------
    def frames(self, zone_colors, gap_x=3000, gap_y=2000):
        cen = [((pl[0][0] + pl[1][0] + pl[2][0]) / 3, (pl[0][1] + pl[1][1] + pl[2][1]) / 3)
               for col, polys in self.geom if col in zone_colors
               for pl in polys if len(pl) == 3]
        cen = np.array(cen)

        def runs(v, gap):
            o = np.sort(v)
            brk = np.where(np.diff(o) > gap)[0]
            res, s = [], o[0]
            for b in brk:
                res.append((s, o[b])); s = o[b + 1]
            res.append((s, o[-1]))
            return res

        out = []
        for xa, xb in runs(cen[:, 0], gap_x):
            m = (cen[:, 0] >= xa) & (cen[:, 0] <= xb)
            if m.sum() < 20:
                continue
            for ya, yb in runs(cen[m, 1], gap_y):
                out.append([float(xa), float(ya), float(xb), float(yb)])
        return out

    def title_rows(self):
        """Sheet titles: the biggest text on the drawing, grouped into rows."""
        if getattr(self, '_rows', None) is not None:
            return self._rows
        if not self.glyphs:
            self._rows = []; return self._rows
        top = max(g['em'] for g in self.glyphs)
        big = [g for g in self.glyphs if g['em'] >= top - 40 and g['t'].strip()]
        rows = []
        for g in sorted(big, key=lambda g: (round(g['y'] / 300), g['x'])):
            for r in rows:
                if abs(r['y'] - g['y']) < 320 and min(abs(g['x'] - m['x']) for m in r['g']) < 4000:
                    r['g'].append(g); break
            else:
                rows.append(dict(y=g['y'], g=[g]))
        for r in rows:
            gs = sorted(r['g'], key=lambda g: -g['x'])     # Hebrew reads right to left
            r['text'] = ' '.join(t for t in (g['t'].strip() for g in gs) if t)
            r['x'] = sum(g['x'] for g in gs) / len(gs)
            r['y'] = min(g['y'] for g in gs)
        self._rows = rows
        return rows

    def assign_titles(self, boxes):
        """One title row per frame: closest pairing, each row used once."""
        rows = self.title_rows()
        pairs = sorted(
            ((abs(r['x'] - (b[0] + b[2]) / 2), i, j)
             for i, b in enumerate(boxes)
             for j, r in enumerate(rows) if b[3] < r['y'] < b[3] + 6000),
            key=lambda t: t[0])
        out = [''] * len(boxes)
        used_f, used_r = set(), set()
        for _d, i, j in pairs:
            if i in used_f or j in used_r:
                continue
            out[i] = re.sub(r'^\d+\s+', '', rows[j]['text']).strip()
            used_f.add(i); used_r.add(j)
        return out

    # -- rasters -------------------------------------------------------------
    def grid(self, box, pad=500):
        x0, y0 = box[0] - pad, box[1] - pad
        w = int((box[2] + pad - x0) / self.upx) + 1
        h = int((box[3] + pad - y0) / self.upx) + 1
        return dict(x0=x0, y0=y0, w=w, h=h)

    def _px(self, g, x, y):
        return ((x - g['x0']) / self.upx, (y - g['y0']) / self.upx)

    def fills(self, g, colors):
        img = Image.new('1', (g['w'], g['h']), 0); dr = ImageDraw.Draw(img)
        X1 = g['x0'] + g['w'] * self.upx; Y1 = g['y0'] + g['h'] * self.upx
        for col, polys in self.geom:
            if col not in colors:
                continue
            for pl in polys:
                if len(pl) != 3:
                    continue
                cx = (pl[0][0] + pl[1][0] + pl[2][0]) / 3
                cy = (pl[0][1] + pl[1][1] + pl[2][1]) / 3
                if not (g['x0'] <= cx <= X1 and g['y0'] <= cy <= Y1):
                    continue
                dr.polygon([self._px(g, *p) for p in pl], fill=1)
        return np.array(img, bool)

    def strokes(self, g, colors, width=1, min_seg=0.0, ortho=False):
        """Raster of the line work.  ``min_seg`` keeps only segments longer than
        that many millimetres, which is what separates the lines that describe
        the building from the lines that describe a tap."""
        img = Image.new('1', (g['w'], g['h']), 0); dr = ImageDraw.Draw(img)
        X1 = g['x0'] + g['w'] * self.upx; Y1 = g['y0'] + g['h'] * self.upx
        lim = min_seg / self.unit_mm
        for col, polys in self.geom:
            if col not in colors:
                continue
            for pl in polys:
                if len(pl) < 2 or not any(g['x0'] <= p[0] <= X1 and g['y0'] <= p[1] <= Y1 for p in pl):
                    continue
                if lim <= 0 and not ortho:
                    dr.line([self._px(g, *p) for p in pl], fill=1, width=width)
                    continue
                for i in range(len(pl) - 1):
                    a, b = pl[i], pl[i + 1]
                    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
                    if ortho and min(dx, dy) > 1.0:
                        continue
                    if max(dx, dy) < lim:
                        continue
                    dr.line([self._px(g, *a), self._px(g, *b)], fill=1, width=width)
        return np.array(img, bool)


    # -- orthogonal line runs -------------------------------------------------
    def ortho_runs(self, box, colors, snap=15, join=30):
        """Collinear, axis-parallel line work merged into maximal runs.

        CAD exports shatter a single wall line into dozens of short segments,
        so nothing can be judged by segment length until they are put back
        together.  Returns {y: [(x0, x1), ...]} for horizontal runs and the
        transpose for vertical ones, in drawing units.
        """
        key = (tuple(sorted(colors)), tuple(box))
        cache = getattr(self, '_runs', None)
        if cache is None:
            cache = self._runs = {}
        if key in cache:
            return cache[key]
        u = lambda mm: mm / self.unit_mm
        x0, y0, x1, y1 = box
        H, V = collections.defaultdict(list), collections.defaultdict(list)
        for col, polys in self.geom:
            if col not in colors:
                continue
            for pl in polys:
                for i in range(len(pl) - 1):
                    (ax, ay), (bx, by) = pl[i], pl[i + 1]
                    if not (x0 <= ax <= x1 and y0 <= ay <= y1):
                        continue
                    if abs(by - ay) <= 1.0 and abs(bx - ax) > 0:
                        H[round((ay + by) / 2, 1)].append((min(ax, bx), max(ax, bx)))
                    elif abs(bx - ax) <= 1.0 and abs(by - ay) > 0:
                        V[round((ax + bx) / 2, 1)].append((min(ay, by), max(ay, by)))

        def collapse(d):
            keys = sorted(d); groups = []
            for k in keys:
                if groups and k - groups[-1][-1] <= u(snap):
                    groups[-1].append(k)
                else:
                    groups.append([k])
            o = {}
            for gp in groups:
                iv = sorted(x for k in gp for x in d[k]); res = []
                for a, b in iv:
                    if res and a <= res[-1][1] + u(join):
                        res[-1][1] = max(res[-1][1], b)
                    else:
                        res.append([a, b])
                o[sum(gp) / len(gp)] = res
            return o

        cache[key] = (collapse(H), collapse(V))
        return cache[key]

    def raster_runs(self, g, box, colors, min_run=500.0, width=1):
        """Raster of only those merged runs long enough to describe a wall."""
        H, V = self.ortho_runs(box, colors)
        lim = min_run / self.unit_mm
        img = Image.new('1', (g['w'], g['h']), 0); dr = ImageDraw.Draw(img)
        for k, iv in H.items():
            for a, b in iv:
                if b - a >= lim:
                    dr.line([self._px(g, a, k), self._px(g, b, k)], fill=1, width=width)
        for k, iv in V.items():
            for a, b in iv:
                if b - a >= lim:
                    dr.line([self._px(g, k, a), self._px(g, k, b)], fill=1, width=width)
        return np.array(img, bool)

    # -- wall detection ------------------------------------------------------
    def wall_pairs(self, box, line_colors, tmin=70, tmax=330, run=400):
        """Walls drawn the way architects draw them: two parallel lines with
        nothing between.  Returns rectangles in drawing units."""
        u = lambda mm: mm / self.unit_mm
        x0, y0, x1, y1 = box
        H, V = collections.defaultdict(list), collections.defaultdict(list)
        for col, polys in self.geom:
            if col not in line_colors:
                continue
            for pl in polys:
                for i in range(len(pl) - 1):
                    (ax, ay), (bx, by) = pl[i], pl[i + 1]
                    if not (x0 <= ax <= x1 and y0 <= ay <= y1):
                        continue
                    if abs(by - ay) <= 1.0 and abs(bx - ax) >= u(100):
                        H[round((ay + by) / 2, 1)].append((min(ax, bx), max(ax, bx)))
                    elif abs(bx - ax) <= 1.0 and abs(by - ay) >= u(100):
                        V[round((ax + bx) / 2, 1)].append((min(ay, by), max(ay, by)))

        def collapse(d):
            keys = sorted(d); groups = []
            for k in keys:
                if groups and k - groups[-1][-1] <= u(15):
                    groups[-1].append(k)
                else:
                    groups.append([k])
            o = {}
            for gp in groups:
                iv = sorted(x for k in gp for x in d[k]); res = []
                for a, b in iv:
                    if res and a <= res[-1][1] + u(30):
                        res[-1][1] = max(res[-1][1], b)
                    else:
                        res.append([a, b])
                o[sum(gp) / len(gp)] = res
            return o

        H, V = collapse(H), collapse(V)
        out = []
        for D, horiz in ((H, True), (V, False)):
            ks = sorted(D)
            for i, k1 in enumerate(ks):
                for k2 in ks[i + 1:]:
                    t = k2 - k1
                    if t < u(tmin):
                        continue
                    if t > u(tmax):
                        break
                    for a1, b1 in D[k1]:
                        for a2, b2 in D[k2]:
                            a, b = max(a1, a2), min(b1, b2)
                            if b - a < u(run):
                                continue
                            blocked = False
                            for km in ks:
                                if k1 + u(25) < km < k2 - u(25):
                                    for c, d in D[km]:
                                        if min(b, d) - max(a, c) > min(u(600), (b - a) * .5):
                                            blocked = True; break
                                if blocked:
                                    break
                            if blocked:
                                continue
                            out.append((a, k1, b, k2) if horiz else (k1, a, k2, b))
        return out

    def thin_bands(self, g, box, line_colors, furn, radius=160, minarea=0.06, min_run=500.0):
        """Walls seen the other way round: the thin empty ribbons that drawn
        lines leave between them."""
        P = lambda mm: max(1, int(round(mm / self.res_mm)))
        L = self.raster_runs(g, box, line_colors, min_run=min_run)
        free = ~L
        # Anything too narrow to hold a disk of radius r is a ribbon, not a room.
        thin = free & ~ndi.binary_opening(free, structure=disk(P(radius)))
        # Wall ribbons meet at junctions, so they arrive as one big network -
        # judge each piece on area and on whether it sits on top of furniture,
        # never on the bounding box of the network it belongs to.
        if furn is not None:
            thin &= ~furn
        lab, n = ndi.label(thin, structure=np.ones((3, 3)))
        if n == 0:
            return thin
        sz = ndi.sum(thin, lab, range(1, n + 1)) * self.m_per_px ** 2
        return np.isin(lab, [i + 1 for i in range(n) if sz[i] >= minarea])

    # -- openings ------------------------------------------------------------
    def door_arcs(self, box, rmin=500, rmax=1400):
        """Door swings.  A leaf arc is a polyline whose points share a centre."""
        x0, y0, x1, y1 = box
        out = []
        for col, polys in self.geom:
            for pl in polys:
                if not (6 <= len(pl) <= 80):
                    continue
                if not (x0 <= pl[0][0] <= x1 and y0 <= pl[0][1] <= y1):
                    continue
                P = np.array(pl)
                span = math.hypot(*(P[-1] - P[0]))
                if span * self.unit_mm < rmin:
                    continue
                # least-squares circle
                A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
                b = (P ** 2).sum(1)
                try:
                    s, *_ = np.linalg.lstsq(A, b, rcond=None)
                except np.linalg.LinAlgError:
                    continue
                cx, cy = s[0], s[1]
                r2 = s[2] + cx * cx + cy * cy
                if r2 <= 0:
                    continue
                r = math.sqrt(r2)
                rr = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
                if rr.std() > 0.02 * r:
                    continue
                R = r * self.unit_mm
                if not (rmin <= R <= rmax):
                    continue
                out.append(dict(cx=float(cx), cy=float(cy), r=float(r),
                                a=[float(P[0][0]), float(P[0][1])],
                                b=[float(P[-1][0]), float(P[-1][1])]))
        return out

    def glazing(self, box, line_colors, gapmax=70, minlen=500):
        """Glass: pairs of parallel lines closer together than any wall."""
        u = lambda mm: mm / self.unit_mm
        x0, y0, x1, y1 = box
        H, V = collections.defaultdict(list), collections.defaultdict(list)
        for col, polys in self.geom:
            if col not in line_colors:
                continue
            for pl in polys:
                for i in range(len(pl) - 1):
                    (ax, ay), (bx, by) = pl[i], pl[i + 1]
                    if not (x0 <= ax <= x1 and y0 <= ay <= y1):
                        continue
                    if abs(by - ay) <= 1.0 and abs(bx - ax) >= u(minlen):
                        H[round((ay + by) / 2, 1)].append((min(ax, bx), max(ax, bx)))
                    elif abs(bx - ax) <= 1.0 and abs(by - ay) >= u(minlen):
                        V[round((ax + bx) / 2, 1)].append((min(ay, by), max(ay, by)))
        out = []
        for D, horiz in ((H, True), (V, False)):
            ks = sorted(D)
            for i, k1 in enumerate(ks):
                for k2 in ks[i + 1:]:
                    t = k2 - k1
                    if t <= u(5):
                        continue
                    if t > u(gapmax):
                        break
                    for a1, b1 in D[k1]:
                        for a2, b2 in D[k2]:
                            a, b = max(a1, a2), min(b1, b2)
                            if b - a < u(minlen):
                                continue
                            out.append((a, k1, b, k2) if horiz else (k1, a, k2, b))
        return out


# ------------------------------------------------------------------ driver --

def build_floor(sh, box, title, zone_colors, line_colors, furn_colors, args):
    P = lambda mm: max(1, int(round(mm / sh.res_mm)))
    g = sh.grid(box)
    mpx = sh.m_per_px

    # A hatch colour counts as an area zone on *this* plan only if it forms a
    # real region here.  The same colour can be a zone on one floor and a stick
    # of furniture on another, so the test is per frame, not per sheet.
    names = getattr(args, '_zone_names', {})
    zones, dropped = {}, {}
    for c in sorted(zone_colors):
        m = sh.fills(g, {c})
        if not m.any():
            continue
        lab_c, nc = ndi.label(m, structure=np.ones((3, 3)))
        biggest = ndi.sum(m, lab_c, range(1, nc + 1)).max() * mpx ** 2
        # A colour straight off the sheet's legend is an area zone by
        # definition; only unnamed candidates have to prove themselves here.
        if biggest < args.min_zone and c not in names:
            dropped[c] = round(float(biggest), 2)
            continue
        zones[c] = m
    furn = sh.fills(g, furn_colors)
    Z = np.zeros((g['h'], g['w']), bool)
    for m in zones.values():
        Z |= m

    # drop stray specks, keep every zone island bigger than 12 m2
    lab, n = ndi.label(Z, structure=np.ones((3, 3)))
    sz = ndi.sum(Z, lab, range(1, n + 1)) * mpx ** 2
    Z = np.isin(lab, [i + 1 for i in range(n) if sz[i] > 12])
    plate = ndi.binary_fill_holes(ndi.binary_closing(Z, structure=disk(P(200))))

    # ---- walls -----------------------------------------------------------
    wall = np.zeros_like(plate)
    for (ax, ay, bx, by) in sh.wall_pairs(box, line_colors):
        j0 = max(0, int((ax - g['x0']) / sh.upx)); j1 = min(g['w'], int(math.ceil((bx - g['x0']) / sh.upx)))
        i0 = max(0, int((ay - g['y0']) / sh.upx)); i1 = min(g['h'], int(math.ceil((by - g['y0']) / sh.upx)))
        sub = furn[i0:i1, j0:j1]
        if sub.size and sub.mean() > 0.15:
            continue
        wall[i0:i1, j0:j1] = True
    wall |= sh.thin_bands(g, box, line_colors, furn, min_run=args.min_run)
    wall &= plate

    outdoor_colors = {c.strip().upper() for c in args.outdoor_colors.split(',') if c.strip()}
    out_zone = np.zeros_like(plate)
    for c in outdoor_colors:
        if c in zones:
            out_zone |= zones[c]

    ring = plate & ~ndi.binary_erosion(plate, structure=disk(P(args.ext_wall)))
    # The run of the ring that borders a balcony is a parapet, not a storey-high
    # wall - a terrace walled to the ceiling is not what the sheet draws.
    parapet = ring & ndi.binary_dilation(out_zone, structure=disk(P(150)))
    ring &= ~parapet
    wall |= ring

    # close junction gaps, never a doorway (a door leaf is at least 700 mm)
    Lg = P(args.bridge)
    wall = (wall | ndi.binary_closing(wall, structure=np.ones((1, Lg), bool))
                 | ndi.binary_closing(wall, structure=np.ones((Lg, 1), bool)))
    wall = ndi.binary_closing(wall, structure=disk(P(60))) & plate

    # A wall belongs to the building's wall network.  Rectangles that float on
    # their own inside a room are furniture outlines, not partitions.
    net = ndi.label(ndi.binary_dilation(wall, structure=disk(P(150))),
                    structure=np.ones((3, 3)))[0]
    keep_ids = set(np.unique(net[ring])) - {0}
    wall &= np.isin(net, list(keep_ids))

    # ---- openings --------------------------------------------------------
    # Glazing.  A window is drawn as thin lines *inside* the wall thickness, so
    # a pair only counts when both of its lines sit clear of the wall faces -
    # that is what separates a window from the wall's own outline.
    core = ndi.binary_erosion(wall, structure=disk(P(45)))
    glass = np.zeros_like(plate)
    for (ax, ay, bx, by) in sh.glazing(box, line_colors, minlen=args.min_window):
        j0 = max(0, int((ax - g['x0']) / sh.upx)); j1 = min(g['w'], int(math.ceil((bx - g['x0']) / sh.upx)))
        i0 = max(0, int((ay - g['y0']) / sh.upx)); i1 = min(g['h'], int(math.ceil((by - g['y0']) / sh.upx)))
        if j1 <= j0 or i1 <= i0:
            continue
        horiz = (j1 - j0) >= (i1 - i0)
        a_ok = core[i0, j0:j1].mean() if horiz else core[i0:i1, j0].mean()
        b_ok = core[i1 - 1, j0:j1].mean() if horiz else core[i0:i1, j1 - 1].mean()
        if min(a_ok, b_ok) < 0.75:
            continue
        if horiz:
            glass[max(0, i0 - P(args.ext_wall)):min(g['h'], i1 + P(args.ext_wall)), j0:j1] = True
        else:
            glass[i0:i1, max(0, j0 - P(args.ext_wall)):min(g['w'], j1 + P(args.ext_wall))] = True
    glass &= wall
    glass_lab, gn = ndi.label(glass, structure=np.ones((3, 3)))
    gsz = ndi.sum(glass, glass_lab, range(1, gn + 1)) * mpx ** 2
    glass = np.isin(glass_lab, [i + 1 for i in range(gn) if 0.10 < gsz[i] < 12.0])

    # Doorways are already gaps in the wall network, because the drawn wall
    # lines stop at them.  Closing the network with a door-sized element finds
    # exactly those gaps, which is where a lintel belongs.
    lint = ndi.binary_closing(wall, structure=disk(P(args.lintel))) & ~wall & plate
    ll, ln = ndi.label(lint, structure=np.ones((3, 3)))
    if ln:
        lsz = ndi.sum(lint, ll, range(1, ln + 1)) * mpx ** 2
        lint = np.isin(ll, [i + 1 for i in range(ln) if lsz[i] < args.max_door_area])
    else:
        lint = np.zeros_like(plate)

    # ---- spaces ----------------------------------------------------------
    # Rooms stay joined through their doorways, so the free space is first
    # pinched apart at anything narrower than a door and then grown back.
    free = plate & ~wall
    free = ndi.binary_opening(free, structure=disk(P(120)))
    r = P(args.door)
    seeds = ndi.binary_opening(free, structure=disk(r))
    sp, ns = ndi.label(seeds, structure=np.ones((3, 3)))
    sp = sp.astype(np.int32)
    for _ in range(r + 4):
        gd = ndi.grey_dilation(sp, footprint=np.ones((3, 3)))
        nxt = np.where((sp == 0) & free, gd, sp)
        if (nxt == sp).all():
            break
        sp = nxt
    sp = np.where(free, sp, 0)
    orphan = free & (sp == 0)
    if orphan.any():
        ol, on = ndi.label(orphan, structure=np.ones((3, 3)))
        sp = np.where(orphan, ol + ns, sp)
        ns += on
    ssz = ndi.sum(free, sp, range(1, ns + 1)) * mpx ** 2
    # Which hatch each space sits on.  The categories overlap - a balcony is
    # inside the residential polygon too - so among the zones that cover a
    # space, the most specific one (smallest on this floor) names it, and a
    # colour straight off the legend beats an anonymous hatch.
    zone_sizes = {c: int(m.sum()) for c, m in zones.items()}
    outer = plate & ~ndi.binary_erosion(plate, structure=np.ones((3, 3)))
    outer = ndi.binary_dilation(outer, structure=disk(P(args.ext_wall + 120)))
    spaces = []
    for i in range(ns):
        if ssz[i] < args.min_space:
            continue
        m = sp == i + 1
        edge = m & ~ndi.binary_erosion(m, structure=np.ones((3, 3)))
        openf = float((edge & outer).sum()) / max(1, int(edge.sum()))
        share = {c: round(float((m & zm).sum()) / max(1, int(m.sum())), 3)
                 for c, zm in zones.items()}
        cand = [c for c, v in share.items() if v >= 0.4]
        cand.sort(key=lambda c: (c not in names, zone_sizes[c]))
        top = cand[0] if cand else (max(share, key=share.get) if share else None)
        ys, xs = np.nonzero(m)
        spaces.append(dict(id=i + 1, area=round(float(ssz[i]), 2),
                           bbox=[float(xs.min() * mpx), float(ys.min() * mpx),
                                 float(xs.max() * mpx), float(ys.max() * mpx)],
                           open_frac=round(openf, 3),
                           zone=top,
                           outdoor=bool(top in outdoor_colors) if top else False,
                           rects=rects_of(m, mpx)))

    # ---- exact areas straight from the hatch geometry --------------------
    s2 = (sh.unit_mm / 1000.0) ** 2
    exact = {}
    for c in zones:
        a = 0.0
        for col, polys in sh.geom:
            if col != c:
                continue
            for pl in polys:
                if len(pl) != 3:
                    continue
                cx = (pl[0][0] + pl[1][0] + pl[2][0]) / 3
                cy = (pl[0][1] + pl[1][1] + pl[2][1]) / 3
                if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
                    a += tri_area(pl) * s2
        if a > 0.5:
            exact[c] = round(a, 2)

    return dict(
        title=title,
        origin=[g['x0'], g['y0']],
        size=[g['w'] * mpx, g['h'] * mpx],
        res=mpx,
        exact_area_m2=exact,
        plate_area_m2=round(float(plate.sum()) * mpx ** 2, 2),
        wall_area_m2=round(float(wall.sum()) * mpx ** 2, 2),
        plate=solid_of(plate, mpx),
        wall=solid_of(wall & ~glass, mpx),           # full height
        wall_under=solid_of(glass, mpx),             # solid below the sill
        wall_over=solid_of(glass | lint, mpx),       # lintel band above the head
        glass=solid_of(glass, mpx),
        wall_rects=rects_of(wall, mpx),              # plan footprint, for collision
        lintel_area_m2=round(float(lint.sum()) * mpx ** 2, 2),
        zones={c: dict(area=exact.get(c, 0.0), rects=rects_of(m, mpx),
                       name=names.get(c, ''))
               for c, m in zones.items()},
        parapet=solid_of(parapet, mpx),
        dropped_colors=dropped,
        furniture=furniture_pieces(furn, wall, plate, mpx),
        spaces=spaces,
    )


def furniture_pieces(furn, wall, plate, mpx):
    """The plan draws furniture as footprints; give each piece the height its
    shape implies.  A stool-sized blob is seating, a mattress-sized one is a
    bed, a shallow long run against a wall is cabinetry, the rest is table
    height.  Heights are furnishing conventions, clearly not measurements."""
    P = lambda mm: max(1, int(round(mm / (mpx * 1000))))
    m = furn & plate
    lab, n = ndi.label(m, structure=np.ones((3, 3)))
    if not n:
        return []
    near_wall = ndi.binary_dilation(wall, structure=disk(P(150)))
    groups = {}
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        if sl is None:
            continue
        piece = lab[sl] == i
        a = piece.sum() * mpx ** 2
        if a < 0.04:
            continue
        h_m = (sl[0].stop - sl[0].start) * mpx
        w_m = (sl[1].stop - sl[1].start) * mpx
        mind, maxd = min(h_m, w_m), max(h_m, w_m)
        wall_frac = (piece & near_wall[sl]).sum() / piece.sum()
        if a < 0.35 or mind < 0.42:
            z = 0.45                                  # chairs, stools, tables' legs
        elif mind >= 1.30 and a >= 2.2:
            z = 0.55                                  # beds
        elif mind <= 0.75 and maxd / mind >= 2.0 and wall_frac >= 0.30:
            z = 0.90                                  # kitchen runs, cabinetry
        else:
            z = 0.72                                  # sofas, dining tables
        g = groups.setdefault(z, np.zeros_like(m))
        g[sl] |= piece
    return [dict(h=z, solid=solid_of(g, mpx)) for z, g in sorted(groups.items())]


def rects_of(mask, mpx, nd=2):
    return [[round(j0 * mpx, nd), round(i0 * mpx, nd),
             round((j1 - j0) * mpx, nd), round((i1 - i0) * mpx, nd)]
            for (i0, j0, i1, j1) in greedy_rects(mask)]


def _runs_along(m, axis):
    """Maximal runs of set cells along ``axis`` for each line of the other one."""
    out = []
    if not m.any():
        return out
    if axis == 0:                       # runs down the rows, one column at a time
        cols = np.flatnonzero(m.any(axis=0))
        for j in cols:
            col = m[:, j]
            idx = np.flatnonzero(col)
            brk = np.flatnonzero(np.diff(idx) > 1)
            starts = np.r_[idx[0], idx[brk + 1]]
            ends = np.r_[idx[brk], idx[-1]] + 1
            for a, b in zip(starts, ends):
                out.append((int(j), int(a), int(b)))
    else:                               # runs across the columns, row by row
        rows = np.flatnonzero(m.any(axis=1))
        for i in rows:
            idx = np.flatnonzero(m[i])
            brk = np.flatnonzero(np.diff(idx) > 1)
            starts = np.r_[idx[0], idx[brk + 1]]
            ends = np.r_[idx[brk], idx[-1]] + 1
            for a, b in zip(starts, ends):
                out.append((int(i), int(a), int(b)))
    return out


def solid_of(mask, mpx, nd=2):
    """A mask as a renderable solid: horizontal caps plus only those vertical
    faces that are actually exposed.

    Emitting every box whole would put two coincident faces between each pair of
    neighbouring boxes, which is what makes extruded floor plans shimmer.
    """
    r = rects_of(mask, mpx, nd)
    faces = []
    sh = lambda a, di, dj: np.roll(np.roll(a, di, 0), dj, 1)
    pad = np.zeros_like(mask)

    def neigh(di, dj):
        n = np.zeros_like(mask)
        if dj == 1:   n[:, :-1] = mask[:, 1:]
        elif dj == -1: n[:, 1:] = mask[:, :-1]
        elif di == 1:  n[:-1, :] = mask[1:, :]
        elif di == -1: n[1:, :] = mask[:-1, :]
        return n

    # faces perpendicular to x: axis 0, plane at the cell edge
    for dj, sgn, off in ((1, 1, 1), (-1, -1, 0)):
        m = mask & ~neigh(0, dj)
        for j, a, b in _runs_along(m, 0):
            faces.append([round((j + off) * mpx, nd), round(a * mpx, nd),
                          round((b - a) * mpx, nd), 0, sgn])
    # faces perpendicular to y: axis 1
    for di, sgn, off in ((1, 1, 1), (-1, -1, 0)):
        m = mask & ~neigh(di, 0)
        for i, a, b in _runs_along(m, 1):
            faces.append([round(a * mpx, nd), round((i + off) * mpx, nd),
                          round((b - a) * mpx, nd), 1, sgn])
    return {'r': r, 'f': faces}


def floor_level(title):
    """Storey number from a sheet title, so floors stack in the right order.

    Understands the Hebrew wording used on Israeli permit sheets and the usual
    English equivalents; anything unrecognised sorts last, in sheet order.
    """
    t = title.strip()
    nums = [int(n) for n in re.findall(r'-?\d+', t)]
    low = t.lower()
    if 'מרתף' in t or 'basement' in low or 'cellar' in low:
        return -abs(nums[0]) if nums else -1
    if 'קרקע' in t or 'ground' in low:
        return 0
    if 'גג' in t or 'roof' in low:
        return 900
    return max(nums) if nums else 999


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('extract_dir')
    ap.add_argument('--out', default='model.json')
    ap.add_argument('--res', type=float, default=20.0, help='raster mm/px')
    ap.add_argument('--height', type=float, default=WALL_H)
    ap.add_argument('--ext-wall', type=float, default=220.0, help='mm')
    ap.add_argument('--bridge', type=float, default=650.0,
                    help='mm; wall gaps narrower than this are junctions, not doors')
    ap.add_argument('--min-space', type=float, default=2.0, help='m2')
    ap.add_argument('--min-zone', type=float, default=8.0,
                    help='m2; a hatch colour whose largest region on a plan is '
                         'smaller than this is furniture, not an area zone')
    ap.add_argument('--outdoor-colors', default='',
                    help='hatch colours that mark balconies / terraces, so those '
                         'spaces render open to the sky behind a parapet')
    ap.add_argument('--zone-names', default='',
                    help="'#HEX=name,...' read off the sheet's own legend; named "
                         'colours are always treated as area zones')
    ap.add_argument('--parapet', type=float, default=1.10, help='m; parapet height')
    ap.add_argument('--min-window', type=float, default=700.0, help='mm')
    ap.add_argument('--lintel', type=float, default=600.0,
                    help='mm; wall gaps this wide or less get a lintel over them')
    ap.add_argument('--max-door-area', type=float, default=2.5, help='m2')
    ap.add_argument('--min-run', type=float, default=500.0,
                    help='mm; shorter line runs describe fittings, not the building')
    ap.add_argument('--door', type=float, default=460.0,
                    help='mm; half a door leaf - spaces are pinched apart at this radius')
    ap.add_argument('--frames', default='', help='comma list of frame indices to keep')
    ap.add_argument('--zone-colors', default='', help='override the detected hatch colours')
    ap.add_argument('--line-colors', default='', help='override the detected line-work colours')
    a = ap.parse_args()

    geom = pickle.load(open(os.path.join(a.extract_dir, 'geometry.pkl'), 'rb'))
    glyphs = json.load(open(os.path.join(a.extract_dir, 'glyphs.json'), encoding='utf-8'))
    meta = json.load(open(os.path.join(a.extract_dir, 'meta.json'), encoding='utf-8'))
    sh = Sheet(geom, glyphs, meta['unit_mm'], a.res)

    fa, fn, ll = sh.color_stats()
    # A colour is line work when it is mostly drawn as polylines; it is an area
    # zone when it is a fine hatch covering tens of square metres.  Both can be
    # pinned down by hand when a sheet does something unusual.
    line_colors = {c for c in ll if ll[c] > 150 and ll[c] > 5 * fa.get(c, 0)}
    if a.line_colors:
        line_colors = {c.strip().upper() for c in a.line_colors.split(',')}
    # Area hatches sit in a narrow band of mean triangle size: coarser than that
    # is a site or background block, finer is a fitting drawn as a solid.  A
    # colour that also draws hundreds of metres of line is line work whose thick
    # pen happens to be filled, not a hatch.
    zone_colors = {c for c in fa
                   if c not in line_colors and ll.get(c, 0) < 300 and fa[c] >= 20
                   and 0.2 <= fa[c] / max(1, fn[c]) <= 3.5}
    if a.zone_colors:
        zone_colors = {c.strip().upper() for c in a.zone_colors.split(',')}
    zone_names = {}
    for part in a.zone_names.split(','):
        if '=' in part:
            c, n = part.split('=', 1)
            zone_names[c.strip().upper()] = n.strip()
    zone_colors |= set(zone_names)
    a._zone_names = zone_names
    def lum(c):
        try:
            return .299 * int(c[1:3], 16) + .587 * int(c[3:5], 16) + .114 * int(c[5:7], 16)
        except Exception:
            return 0
    # Near-white fills are wipe-outs and wall poche, not furniture: masking them
    # out would erase the very partitions we are looking for.
    furn_colors = {c for c in fa if c not in zone_colors and c not in line_colors
                   and 0.2 < fa[c] < 400 and lum(c) < 235}
    print('zone colours :', [(c, round(fa[c])) for c in sorted(zone_colors, key=lambda c: -fa[c])])
    print('line colours :', [(c, round(ll[c])) for c in sorted(line_colors, key=lambda c: -ll[c])][:8])

    frames = sh.frames(zone_colors)
    titles = sh.assign_titles(frames)
    keep = set(int(i) for i in a.frames.split(',') if i.strip() != '') if a.frames else None
    floors = []
    for i, box in enumerate(frames):
        if keep is not None and i not in keep:
            continue
        t = titles[i]
        print(f'[{i}] {box[0]:.0f},{box[1]:.0f} .. {box[2]:.0f},{box[3]:.0f}   {t}')
        f = build_floor(sh, box, t, zone_colors, line_colors, furn_colors, a)
        if f['plate_area_m2'] < 10:      # a legend or a stray swatch, not a plan
            print('      skipped - no floor plate here')
            continue
        f['index'] = i
        f['level'] = floor_level(t)
        floors.append(f)
        print(f'      plate {f["plate_area_m2"]} m2   walls {f["wall_area_m2"]} m2   '
              f'spaces {len(f["spaces"])}   exact {f["exact_area_m2"]}')

    floors.sort(key=lambda f: (f['level'], f['index']))
    model = dict(source=meta.get('source'), unit_mm=meta['unit_mm'],
                 plot_scale=meta.get('plot_scale'),
                 wall_height=a.height, sill=SILL, head=HEAD, slab=SLAB,
                 parapet=a.parapet,
                 zone_colors=sorted(zone_colors), zone_names=zone_names,
                 floors=floors)
    json.dump(model, open(a.out, 'w'), separators=(',', ':'))
    print('wrote', a.out, os.path.getsize(a.out) // 1024, 'KB')


if __name__ == '__main__':
    main()
