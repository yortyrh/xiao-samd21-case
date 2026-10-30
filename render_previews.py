"""
Renders the README preview images into images/.
Small orthographic z-buffer rasterizer (numpy only), with diffuse shading and
edge outlines, so no extra rendering dependency is needed.

Usage:  uv run render_previews.py
"""
import struct
import zlib
from pathlib import Path

import numpy as np

import xiao_samd21_case as c

OUT_DIR = Path("images")
WIDTH = 900           # output width in px (height follows the model)
SSAA = 2              # supersampling factor for anti-aliasing
MARGIN = 0.06
CASE_COLOR = (0.23, 0.51, 0.96)
LID_COLOR = (0.38, 0.65, 0.98)
PCB_COLOR = (0.12, 0.44, 0.25)
USB_COLOR = (0.75, 0.77, 0.80)
HEADER_COLOR = (0.16, 0.16, 0.18)
EDGE_COLOR = np.array((0.08, 0.10, 0.16))


def camera(elev, azim):
    """Orthonormal view basis (right, up, toward camera) from elevation/azimuth in degrees."""
    e, a = np.radians(elev), np.radians(azim)
    d = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    right = np.array([-np.sin(a), np.cos(a), 0.0])
    up = np.cross(d, right)
    return right, up, d


def triangles(m):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    return v[np.asarray(mesh.tri_verts)]


def render(parts, path, elev, azim):
    right, up, d = camera(elev, azim)
    light = 0.55 * d + 0.6 * up - 0.35 * right
    light /= np.linalg.norm(light)

    tris = np.vstack([triangles(m) for m, _ in parts])
    colors = np.vstack([np.tile(col, (len(triangles(m)), 1)) for m, col in parts])
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)

    # project to screen space
    sx, sy, sz = tris @ right, tris @ up, tris @ d
    lo = np.array([sx.min(), sy.min()])
    hi = np.array([sx.max(), sy.max()])
    w = WIDTH * SSAA
    scale = w * (1 - 2 * MARGIN) / (hi[0] - lo[0])
    h = int(np.ceil((hi[1] - lo[1]) * scale + 2 * MARGIN * w))
    px = (sx - lo[0]) * scale + MARGIN * w
    py = h - ((sy - lo[1]) * scale + MARGIN * w)

    zbuf = np.full((h, w), -np.inf)
    rgb = np.zeros((h, w, 3))
    nbuf = np.zeros((h, w, 3))
    shade = 0.35 + 0.65 * np.clip(normals @ light, 0, 1)

    for i in np.nonzero(normals @ d > 1e-6)[0]:   # back faces are never visible
        x0, x1, x2 = px[i]
        y0, y1, y2 = py[i]
        xmin, xmax = int(max(np.floor(min(x0, x1, x2)), 0)), int(min(np.ceil(max(x0, x1, x2)), w - 1))
        ymin, ymax = int(max(np.floor(min(y0, y1, y2)), 0)), int(min(np.ceil(max(y0, y1, y2)), h - 1))
        if xmin > xmax or ymin > ymax:
            continue
        gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        z = l0 * sz[i, 0] + l1 * sz[i, 1] + l2 * sz[i, 2]
        region = zbuf[ymin:ymax + 1, xmin:xmax + 1]
        win = inside & (z > region)
        region[win] = z[win]
        rgb[ymin:ymax + 1, xmin:xmax + 1][win] = colors[i] * shade[i]
        nbuf[ymin:ymax + 1, xmin:xmax + 1][win] = normals[i]

    # outlines where the surface normal or depth jumps, or at the silhouette
    covered = np.isfinite(zbuf)
    z = np.where(covered, zbuf, zbuf[covered].min() - 10)
    edge = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (1, 0)):
        n2 = np.roll(nbuf, (-dy, -dx), axis=(0, 1))
        z2 = np.roll(z, (-dy, -dx), axis=(0, 1))
        c2 = np.roll(covered, (-dy, -dx), axis=(0, 1))
        e = ((nbuf * n2).sum(axis=2) < 0.8) | (np.abs(z - z2) > 0.6) | (covered != c2)
        edge |= e | np.roll(e, (dy, dx), axis=(0, 1))
    edge &= covered
    rgb[edge] = rgb[edge] * 0.3 + EDGE_COLOR * 0.7

    # downsample (SSAA) to RGBA
    rgba = np.dstack([rgb, covered.astype(float)])
    rgba[..., :3] *= rgba[..., 3:]
    h2 = h // SSAA
    rgba = rgba[:h2 * SSAA].reshape(h2, SSAA, WIDTH, SSAA, 4).mean(axis=(1, 3))
    alpha = rgba[..., 3:]
    rgba[..., :3] = np.where(alpha > 0, rgba[..., :3] / np.maximum(alpha, 1e-9), 0)
    write_png((np.clip(rgba, 0, 1) * 255).round().astype(np.uint8), path)
    print(path)


def write_png(img, path):
    h, w, _ = img.shape
    raw = b"".join(b"\0" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def board(z0):
    """Simple XIAO stand-in: PCB, USB-C receptacle and (optionally) pin headers."""
    pcb = c.box(c.PCB_L, c.PCB_W, c.PCB_T, z=z0)
    usb = c.box(7.4, c.USB_W, c.USB_H, x=-c.PCB_L / 2 - c.USB_OVERHANG + 3.7, z=z0 + c.PCB_T)
    parts = [(pcb, PCB_COLOR), (usb, USB_COLOR)]
    if c.HEADERS:
        for s in (-1, 1):
            hdr = c.box(c.PINS * c.PIN_PITCH, c.PIN_PITCH, c.HEADER_H, y=s * c.PIN_ROW_Y, z=z0 - c.HEADER_H)
            parts.append((hdr, HEADER_COLOR))
    return parts


def cut_half(m):
    """Remove the y > 0 half so the inside is visible from the +Y side."""
    return m - c.box(100, 50, 100, y=25, z=-50)


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    base = c.base()
    lid = c.lid()

    render([(base, CASE_COLOR), (lid.translate((0, 0, c.BASE_H)), LID_COLOR)],
           OUT_DIR / "assembled.png", elev=25, azim=-140)
    render([(base, CASE_COLOR), *board(c.PCB_Z + 8),
            (lid.translate((0, 0, c.BASE_H + 20)), LID_COLOR)],
           OUT_DIR / "exploded.png", elev=20, azim=-140)
    seated = board(c.PCB_Z)
    render([(base, CASE_COLOR), *seated], OUT_DIR / "board_in_base.png", elev=50, azim=-125)
    section = [(cut_half(base), CASE_COLOR), *[(cut_half(m), col) for m, col in seated],
               (cut_half(lid.translate((0, 0, c.BASE_H))), LID_COLOR)]
    render(section, OUT_DIR / "cutaway.png", elev=22, azim=70)
    render([(base, CASE_COLOR)], OUT_DIR / "base.png", elev=55, azim=-120)
    render([(lid.rotate((180, 0, 0)), LID_COLOR)], OUT_DIR / "lid_bottom.png", elev=45, azim=-120)
