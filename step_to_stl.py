"""
Converts a STEP board model into one binary STL per solid, mirrored in X so the
USB-C ends up at -X like in the case. Used by render_previews.py for the board images.

Usage:  uv run --no-project --python 3.12 --with cadquery-ocp step_to_stl.py "model.step" board_model/
The STEP is not part of the repo (third-party model), so neither are the STLs.
"""
import struct
import sys
from pathlib import Path

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


def solid_triangles(solid):
    BRepMesh_IncrementalMesh(solid, 0.02, False, 0.3, True)
    out = []
    faces = TopExp_Explorer(solid, TopAbs_FACE)
    while faces.More():
        face = TopoDS.Face(faces.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            pts = []
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                pts.append((p.X(), p.Y(), p.Z()))
            pts = np.array(pts)
            flip = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                idx = (a - 1, c - 1, b - 1) if flip else (a - 1, b - 1, c - 1)
                out.append(pts[list(idx)])
        faces.Next()
    return np.array(out)


def write_stl(tris, path):
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for p0, p1, p2 in tris:
            n = np.cross(p1 - p0, p2 - p0)
            nn = np.linalg.norm(n)
            n = n / nn if nn else n
            f.write(struct.pack("<12fH", *n, *p0, *p1, *p2, 0))


if __name__ == "__main__":
    src, dst = sys.argv[1], Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    reader = STEPControl_Reader()
    reader.ReadFile(src)
    reader.TransferRoots()
    solids = TopExp_Explorer(reader.OneShape(), TopAbs_SOLID)
    i = 0
    while solids.More():
        t = solid_triangles(solids.Current())
        t[..., 0] *= -1                 # mirror X ...
        t = t[:, ::-1]                  # ... and restore the winding
        write_stl(t, dst / f"part{i}.stl")
        print(dst / f"part{i}.stl", len(t), "triangles")
        solids.Next()
        i += 1
