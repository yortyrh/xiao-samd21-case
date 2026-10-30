"""
Case for the Seeed Studio XIAO SAMD21 (Seeeduino XIAO).
Generates the base (with header slots) and the snap-fit lid as STL and 3MF,
plus one 3MF with both parts ready to print together.

Usage:  uv run xiao_samd21_case.py
All dimensions in mm. Check them with calipers before printing.
"""
import struct
import zipfile
import numpy as np
from manifold3d import Manifold, OpType

# --- XIAO SAMD21 -------------------------------------------------------------
PCB_L = 21.3          # length (X axis, USB-C at -X)
PCB_W = 17.9          # width (Y axis)
PCB_T = 1.6           # PCB thickness
USB_W = 9.0           # USB-C receptacle
USB_H = 2.9           # above the PCB top face
USB_OVERHANG = 1.3    # how far the USB-C sticks out past the PCB edge
PIN_PITCH = 2.54
PIN_ROW_Y = 15.24 / 2  # pin rows at +-7.62 from center
PINS = 7

# --- Case --------------------------------------------------------------------
HEADERS = True        # True: raise the PCB by the header height
HEADER_SLOTS = False  # True: cut floor slots for the male headers (fits a breadboard)
HEADER_H = 2.5        # header plastic height (= PCB height above the bottom)
CLR = 0.25            # PCB-to-wall clearance
WALL = 1.6
FLOOR = 1.2
TOP_CLR = 3.6         # space above the PCB (USB-C is 3.2 tall)
LID_T = 1.2
LIP_H = 1.5           # lid lip that goes into the base
LIP_T = 1.0
LIP_CLR = 0.15        # fit clearance (raise to 0.2 if too tight)
USB_OPEN_W = 9.8
USB_RECESS_W, USB_RECESS_H, USB_RECESS_D = 12.6, 7.0, 0.8  # recess for the cable overmold
# lid windows for LEDs / RESET pads (on both sides of the USB-C)
WIN_L, WIN_W = 5.0, 3.6
WIN_X_FROM_USB_END = 0.8   # from the USB edge of the PCB
WIN_Y = 6.2                # center of each window, +-Y

# name engraved in the floor, where the header slots used to be
ENGRAVE_TEXT = True
ENGRAVE_DEPTH = 0.4
ENGRAVE_H = 7.0       # letter height
ENGRAVE_STROKE = 1.2
ENGRAVE_GAP = 1.2     # between letters

# smile on the lid top: the two LED windows are the eyes
SMILE = True
SMILE_DEPTH = 0.4
SMILE_STROKE = 1.2
SMILE_R = 7.0         # radius of the mouth arc
SMILE_HALF_ANGLE = 55  # degrees each side of the arc center
SMILE_CX = -2.0       # arc center X (the mouth bulges towards +X, away from the eyes)

SEG = 48

IN_L = PCB_L + 2 * CLR
IN_W = PCB_W + 2 * CLR
OUT_L = IN_L + 2 * WALL
OUT_W = IN_W + 2 * WALL
PCB_Z = HEADER_H if HEADERS else FLOOR + 1.0     # PCB bottom face
BASE_H = PCB_Z + PCB_T + TOP_CLR
USB_Z = PCB_Z + PCB_T + USB_H / 2               # USB-C center


def box(sx, sy, sz, x=0.0, y=0.0, z=0.0):
    """Box centered in XY, resting on z."""
    return Manifold.cube((sx, sy, sz), center=True).translate((x, y, z + sz / 2))


def rbox(sx, sy, sz, r, x=0.0, y=0.0, z=0.0):
    """Box with rounded vertical edges."""
    r = min(r, sx / 2 - 0.01, sy / 2 - 0.01)
    c = Manifold.cylinder(sz, r, r, SEG)
    parts = [c.translate((dx * (sx / 2 - r), dy * (sy / 2 - r), 0))
             for dx in (-1, 1) for dy in (-1, 1)]
    hull = Manifold.batch_hull(parts)
    return hull.translate((x, y, z))


def engrave_lulu():
    """'Lulu' as a cutter on the bottom face, readable looking at the base from below.

    Letters are built from boxes and rings in text coordinates (tx right, ty up),
    then mirrored in X because the bottom face is seen from -Z.
    """
    h, st, gap = ENGRAVE_H, ENGRAVE_STROKE, ENGRAVE_GAP
    uw = 3.6              # width of a "u"
    ux = 4.5              # x-height of a "u"
    d = ENGRAVE_DEPTH + 1.0   # cutter pokes out below z=0

    def bar(x0, y0, w, hh):
        return box(w, hh, d, x=x0 + w / 2, y=y0 + hh / 2, z=-1)

    def letter_L(x):
        return bar(x, 0, st, h) + bar(x, 0, uw, st), uw

    def letter_l(x):
        return bar(x, 0, st, h), st

    def letter_u(x):
        ro = uw / 2
        ring = Manifold.cylinder(d, ro, ro, SEG) - Manifold.cylinder(d, ro - st, ro - st, SEG)
        # lower half of the ring is the bowl; two stems go up to the x-height
        bowl = ring.translate((x + ro, ro, -1)) ^ bar(x, 0, uw, ro)
        stems = bar(x, ro, st, ux - ro) + bar(x + uw - st, ro, st, ux - ro)
        return bowl + stems, uw

    cutter, x = None, 0.0
    for build in (letter_L, letter_u, letter_l, letter_u):
        part, w = build(x)
        cutter = part if cutter is None else cutter + part
        x += w + gap
    total = x - gap
    # center in the footprint of the old header slots, mirror X
    cutter = cutter.translate((-total / 2, -h / 2, 0))
    return cutter.mirror((1, 0, 0))


def smile():
    """Mouth arc cutter for the lid top (z = LID_T), round-capped, opening towards the eyes."""
    r = SMILE_STROKE / 2
    n = 16
    dots = []
    for i in range(n + 1):
        a = np.radians(-SMILE_HALF_ANGLE + 2 * SMILE_HALF_ANGLE * i / n)
        dots.append(Manifold.cylinder(SMILE_DEPTH + 1, r, r, 24).translate(
            (SMILE_CX + SMILE_R * np.cos(a), SMILE_R * np.sin(a), LID_T - SMILE_DEPTH)))
    return Manifold.batch_boolean([Manifold.batch_hull(dots[i:i + 2]) for i in range(n)], OpType.Add)


def base():
    b = rbox(OUT_L, OUT_W, BASE_H, 2.0)
    # cavity
    b -= box(IN_L, IN_W, BASE_H, z=FLOOR)
    # PCB supports at the short ends (outside the pin rows)
    slot_len = PINS * PIN_PITCH + 0.6
    ledge = (IN_L - slot_len) / 2 - 0.1
    for s in (-1, 1):
        b += box(ledge, IN_W, PCB_Z - FLOOR, x=s * (IN_L - ledge) / 2, z=FLOOR)
    # center support
    b += box(4.0, 6.0, PCB_Z - FLOOR, z=FLOOR)
    if HEADER_SLOTS:
        for s in (-1, 1):
            b -= box(slot_len, 2.9, FLOOR + 2, y=s * PIN_ROW_Y, z=-1)
    if ENGRAVE_TEXT:
        b -= engrave_lulu()
    # U-shaped USB-C opening, open at the top (the PCB drops in from above)
    usb_bot = USB_Z - (USB_H + 0.6) / 2
    b -= box(WALL + 2, USB_OPEN_W, BASE_H, x=-OUT_L / 2, z=usb_bot)
    b -= rbox(USB_RECESS_D * 2, USB_RECESS_W, BASE_H, 1.0,
              x=-OUT_L / 2, z=USB_Z - USB_RECESS_H / 2)
    return b


def lid():
    l = rbox(OUT_L, OUT_W, LID_T, 2.0)
    # perimeter lip (towards -Z)
    lo = box(IN_L - 2 * LIP_CLR, IN_W - 2 * LIP_CLR, LIP_H, z=-LIP_H)
    li = box(IN_L - 2 * LIP_CLR - 2 * LIP_T, IN_W - 2 * LIP_CLR - 2 * LIP_T, LIP_H + 1, z=-LIP_H - 0.5)
    lip = lo - li
    # remove the lip on the USB side (it hits the connector)
    lip -= box(LIP_T + 2, USB_OPEN_W + 1, LIP_H + 1, x=-IN_L / 2, z=-LIP_H - 0.5)
    l += lip
    # posts that press the PCB down at the 4 corners
    post_h = TOP_CLR - 0.2
    for sx in (-1, 1):
        for sy in (-1, 1):
            l += box(1.6, 1.6, post_h,
                     x=sx * (PCB_L / 2 - 1.2), y=sy * (PCB_W / 2 - 1.2), z=-post_h)
    # LED / RESET windows
    wx = -PCB_L / 2 + WIN_X_FROM_USB_END + WIN_L / 2
    for s in (-1, 1):
        l -= rbox(WIN_L, WIN_W, LID_T + 2, 0.8, x=wx, y=s * WIN_Y, z=-1)
    if SMILE:
        l -= smile()
    return l


def write_stl(m, path):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    t = np.asarray(mesh.tri_verts)
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(t)))
        for a, b_, c in t:
            p0, p1, p2 = v[a], v[b_], v[c]
            n = np.cross(p1 - p0, p2 - p0)
            nn = np.linalg.norm(n)
            n = n / nn if nn else n
            f.write(struct.pack("<12fH", *n, *p0, *p1, *p2, 0))
    print(f"{path}: {len(t)} triangles, volume {m.volume():.1f} mm3")


_3MF_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

_3MF_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def write_3mf(parts, path):
    """parts: list of (name, Manifold). Each part is a separate object."""
    objs, items = [], []
    for i, (name, m) in enumerate(parts, start=1):
        mesh = m.to_mesh()
        v = np.asarray(mesh.vert_properties)[:, :3]
        t = np.asarray(mesh.tri_verts)
        verts = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in v)
        tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t)
        objs.append(f'<object id="{i}" name="{name}" type="model"><mesh>'
                    f'<vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object>')
        items.append(f'<item objectid="{i}"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources>{"".join(objs)}</resources><build>{"".join(items)}</build></model>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _3MF_CONTENT_TYPES)
        z.writestr("_rels/.rels", _3MF_RELS)
        z.writestr("3D/3dmodel.model", model)
    print(f"{path}: {len(parts)} part(s)")


if __name__ == "__main__":
    b = base()
    # lid flipped: top face on the print bed
    lid_print = lid().rotate((180, 0, 0)).translate((0, 0, LID_T))
    write_stl(b, "xiao_samd21_base.stl")
    write_stl(lid_print, "xiao_samd21_lid.stl")
    write_3mf([("base", b)], "xiao_samd21_base.3mf")
    write_3mf([("lid", lid_print)], "xiao_samd21_lid.3mf")
    # both parts on the same plate, 5 mm apart in Y
    gap = OUT_W + 5
    write_3mf([("base", b.translate((0, -gap / 2, 0))),
               ("lid", lid_print.translate((0, gap / 2, 0)))], "xiao_samd21_case.3mf")
    print(f"Outer size: {OUT_L:.1f} x {OUT_W:.1f} x {BASE_H + LID_T:.1f} mm")
