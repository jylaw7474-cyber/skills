#!/usr/bin/env python3
"""
Stage 1 - dwfx_extract.py
Unpack a DWF/DWFx (Autodesk ePlot, an OPC/XPS package) and pull out every
drawing primitive as plain geometry.

Output (written next to --out):
    geometry.pkl   list[ (color, [polyline, ...]) ]  in drawing units
    glyphs.json    list[ {x, y, t, em, font} ]       text with placement
    meta.json      page size, layer table, named views, unit scale

Nothing is interpreted here - this stage is a faithful reader.
"""
import argparse, html, json, math, os, pickle, re, shutil, sys, tempfile, zipfile

NUM = r'-?\d*\.?\d+(?:[eE][-+]?\d+)?'
TOK = re.compile(r'[A-Za-z]|' + NUM)
ATTR = re.compile(r'(\w[\w:.-]*)="([^"]*)"')


def parse_path_data(d):
    """XPS/SVG mini-language -> list of polylines. Curves are flattened."""
    toks = TOK.findall(d)
    i = 0
    cur = start = None
    polys, poly, cmd = [], [], None

    def f():
        nonlocal i
        v = float(toks[i]); i += 1
        return v

    while i < len(toks):
        t = toks[i]
        if len(t) == 1 and t.isalpha():
            cmd = t; i += 1
            if cmd in 'Ff':                      # fill-rule prefix
                i += 1; continue
            if cmd in 'Zz':
                if poly and start:
                    poly.append(start)
                if len(poly) > 1:
                    polys.append(poly)
                poly = [start] if start else []
                cur = start
                continue
        if cmd is None:
            i += 1; continue
        if cmd in 'Mm':
            x, y = f(), f()
            if cmd == 'm' and cur: x += cur[0]; y += cur[1]
            if len(poly) > 1: polys.append(poly)
            cur = start = (x, y); poly = [cur]
        elif cmd in 'Ll':
            x, y = f(), f()
            if cmd == 'l': x += cur[0]; y += cur[1]
            cur = (x, y); poly.append(cur)
        elif cmd in 'Hh':
            x = f()
            if cmd == 'h': x += cur[0]
            cur = (x, cur[1]); poly.append(cur)
        elif cmd in 'Vv':
            y = f()
            if cmd == 'v': y += cur[1]
            cur = (cur[0], y); poly.append(cur)
        elif cmd in 'Cc':
            p = [f() for _ in range(6)]
            if cmd == 'c':
                p = [p[k] + (cur[0] if k % 2 == 0 else cur[1]) for k in range(6)]
            p0, p1, p2, p3 = cur, (p[0], p[1]), (p[2], p[3]), (p[4], p[5])
            for k in range(1, 9):
                u = k / 8.0; v = 1 - u
                poly.append((v**3*p0[0] + 3*v*v*u*p1[0] + 3*v*u*u*p2[0] + u**3*p3[0],
                             v**3*p0[1] + 3*v*v*u*p1[1] + 3*v*u*u*p2[1] + u**3*p3[1]))
            cur = p3
        elif cmd in 'Qq':
            p = [f() for _ in range(4)]
            if cmd == 'q':
                p = [p[k] + (cur[0] if k % 2 == 0 else cur[1]) for k in range(4)]
            p0, p1, p2 = cur, (p[0], p[1]), (p[2], p[3])
            for k in range(1, 7):
                u = k / 6.0; v = 1 - u
                poly.append((v*v*p0[0] + 2*v*u*p1[0] + u*u*p2[0],
                             v*v*p0[1] + 2*v*u*p1[1] + u*u*p2[1]))
            cur = p2
        elif cmd in 'Ss':
            p = [f() for _ in range(4)]
            if cmd == 's':
                p = [p[k] + (cur[0] if k % 2 == 0 else cur[1]) for k in range(4)]
            cur = (p[2], p[3]); poly.append(cur)
        elif cmd in 'Aa':
            f(); f(); f(); f(); f(); x, y = f(), f()
            if cmd == 'a': x += cur[0]; y += cur[1]
            cur = (x, y); poly.append(cur)
        else:
            i += 1
    if len(poly) > 1:
        polys.append(poly)
    return polys


def apply(m, polys):
    a, b, c, d, e, f_ = m
    return [[(a*x + c*y + e, b*x + d*y + f_) for x, y in pl] for pl in polys]


def read_package(path, workdir):
    with zipfile.ZipFile(path) as z:
        z.extractall(workdir)
    fpage = w2x = desc = None
    for root, _, files in os.walk(workdir):
        for fn in files:
            p = os.path.join(root, fn)
            if fn.endswith('.fpage'):
                fpage = p
            elif fn == 'descriptor.xml' and b'GraphicResource' in open(p, 'rb').read():
                desc = p
            elif fn.endswith('.xml') and os.path.getsize(p) > 50000:
                if b'<W2X' in open(p, 'rb').read(200):
                    w2x = p
    if not fpage:
        sys.exit('no FixedPage (.fpage) found - is this a 2D DWF/DWFx?')
    return fpage, w2x, desc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dwfx')
    ap.add_argument('--out', default='out')
    ap.add_argument('--scale', type=float, default=None,
                    help='mm of real world per drawing unit; auto-calibrated when omitted')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp()
    try:
        fpage, w2x, desc = read_package(a.dwfx, work)
        src = open(fpage, encoding='utf-8', errors='replace').read()

        geom = []
        for tag in re.findall(r'<Path\b[^>]*/>', src):
            at = dict(ATTR.findall(tag))
            d = at.get('Data')
            if not d:
                continue
            color = at.get('Fill') or at.get('Stroke') or '#000000'
            polys = parse_path_data(d)
            rt = at.get('RenderTransform')
            if rt:
                polys = apply([float(v) for v in rt.split(',')], polys)
            geom.append((color.upper(), polys))

        glyphs = []
        for tag in re.findall(r'<Glyphs\b[^>]*/>', src):
            at = dict(ATTR.findall(tag))
            ox, oy = float(at.get('OriginX', 0)), float(at.get('OriginY', 0))
            rt = at.get('RenderTransform')
            if rt:
                m = [float(v) for v in rt.split(',')]
                x = m[0]*ox + m[2]*oy + m[4]
                y = m[1]*ox + m[3]*oy + m[5]
                sy = abs(m[3]) or abs(m[1]) or 1.0
            else:
                x, y, sy = ox, oy, 1.0
            glyphs.append({'x': round(x, 2), 'y': round(y, 2),
                           't': html.unescape(at.get('UnicodeString', '')),
                           'em': round(float(at.get('FontRenderingEmSize', 0)) * sy, 1),
                           'font': at.get('FontUri', '')[2:10]})

        meta = {'source': os.path.basename(a.dwfx)}
        m = re.search(r'<FixedPage[^>]*Width="([\d.]+)"[^>]*', src) or \
            re.search(r'<FixedPage[^>]*', src)
        pw = re.search(r'Width="([\d.]+)"', m.group(0)) if m else None
        ph = re.search(r'Height="([\d.]+)"', m.group(0)) if m else None
        meta['page'] = {'w': float(pw.group(1)) if pw else None,
                        'h': float(ph.group(1)) if ph else None}
        if w2x:
            wx = open(w2x, encoding='utf-8', errors='replace').read()
            meta['layers'] = [dict(ATTR.findall(t)) for t in re.findall(r'<Layer[^>]*>', wx)
                              if 'Name=' in t]
            meta['named_views'] = [dict(ATTR.findall(t))
                                   for t in re.findall(r'<Named_View[^>]*>', wx)]

        paper = None
        if desc:
            dm = re.search(r'GraphicResource[^>]*transform="([\d.eE+-]+)', 
                           open(desc, encoding='utf-8', errors='replace').read())
            if dm:
                paper = float(dm.group(1))      # mm of paper per drawing unit
        meta['paper_mm_per_unit'] = paper
        meta['unit_mm'] = a.scale if a.scale else calibrate(geom, glyphs, paper)
        if paper:
            meta['plot_scale'] = round(meta['unit_mm'] / paper)

        pickle.dump(geom, open(os.path.join(a.out, 'geometry.pkl'), 'wb'))
        json.dump(glyphs, open(os.path.join(a.out, 'glyphs.json'), 'w'), ensure_ascii=False)
        json.dump(meta, open(os.path.join(a.out, 'meta.json'), 'w'), ensure_ascii=False, indent=1)
        print(f'paths={len(geom)}  glyphs={len(glyphs)}  unit_mm={meta["unit_mm"]:.5f}')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def calibrate(geom, glyphs, paper=None):
    """Recover mm-per-drawing-unit by matching dimension texts to dimension lines.

    A plotted CAD sheet carries its own ruler: every dimension string states the
    true length of the line it labels.  The modal text/length ratio is the scale.
    """
    import bisect, collections
    segs = []
    for _c, polys in geom:
        for pl in polys:
            if len(pl) != 2:
                continue
            (x1, y1), (x2, y2) = pl
            if abs(y2 - y1) > 2 and abs(x2 - x1) > 2:
                continue
            d = math.hypot(x2 - x1, y2 - y1)
            if d > 50:
                segs.append((min(x1, x2), (x1 + x2) / 2, (y1 + y2) / 2, d))
    segs.sort()
    sx = [s[0] for s in segs]
    hits = collections.Counter()
    for g in glyphs:
        t = g['t']
        if not t.isdigit():
            continue
        v = int(t)
        if not (80 <= v <= 1500):
            continue
        lo = bisect.bisect_left(sx, g['x'] - 2000)
        hi = bisect.bisect_right(sx, g['x'] + 2000)
        for _a, mx, my, d in segs[lo:hi]:
            if abs(mx - g['x']) < 250 and abs(my - g['y']) < 250:
                hits[round(v * 10.0 / d, 3)] += 1
    if not hits:
        return 1.0
    if paper:
        # A plotted sheet uses a round scale.  Score each candidate 1:S by how
        # many dimension strings agree with it to within 1%.
        best, score = None, -1
        for S in (1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 500, 1000):
            cand = paper * S
            n = sum(c for r, c in hits.items() if abs(r - cand) <= 0.01 * cand)
            if n > score:
                best, score = cand, n
        if score >= 5:
            return best
    return hits.most_common(1)[0][0]


if __name__ == '__main__':
    main()
