#!/usr/bin/env python3
"""Flat PNG preview of a model.json - the fastest way to see whether the
extraction agrees with the drawing before spending time in 3D."""
import argparse, json
from PIL import Image, ImageDraw

C = dict(plate=(226, 232, 240), zone=(210, 224, 244), furniture=(240, 226, 205),
         wall=(38, 40, 46), glass=(90, 165, 210), space=None)
PALETTE = [(214,232,244),(238,226,212),(216,238,220),(244,234,208),(230,220,244),
           (208,238,240),(246,222,232),(226,236,214),(240,214,214),(214,222,240)]


def draw(fl, px_per_m, out):
    W = int(fl['size'][0] * px_per_m) + 1
    H = int(fl['size'][1] * px_per_m) + 1
    img = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(img)
    def rects(rs, col):
        if isinstance(rs, dict):      # a solid: caps plus exposed faces
            rs = rs['r']
        for x, y, w, h in rs:
            d.rectangle([x*px_per_m, y*px_per_m, (x+w)*px_per_m, (y+h)*px_per_m], fill=col)
    rects(fl['plate'], C['plate'])
    for i, sp in enumerate(sorted(fl['spaces'], key=lambda s: -s['area'])):
        rects(sp['rects'], (168, 208, 186) if sp.get('outdoor') else PALETTE[i % len(PALETTE)])
    rects(fl['furniture'], C['furniture'])
    rects(fl['wall'], C['wall'])
    rects(fl['wall_under'], C['wall'])
    rects(fl['glass'], C['glass'])
    img.save(out)
    return img.size


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('model'); ap.add_argument('--index', type=int, default=0)
    ap.add_argument('--px', type=float, default=40.0, help='pixels per metre')
    ap.add_argument('--out', default='preview.png')
    a = ap.parse_args()
    m = json.load(open(a.model))
    fl = [f for f in m['floors'] if f['index'] == a.index][0]
    print(fl['title'], draw(fl, a.px, a.out))
