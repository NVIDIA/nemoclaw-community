# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Score a saved CAD reconstruction by IoU against the reference mesh.

Usage, with a Python that can import FreeCAD (the task image's ``python``)::

    python score.py model.FCStd reference_mesh.obj

Output contract:

* success -> one number in ``0.0`` - ``1.0`` on stdout, exit 0
* failure -> nothing on stdout, a ``# <reason>`` line on stderr, exit 2

A failure prints no number on purpose. An earlier revision printed ``0.0`` on
both paths, which makes "could not measure" indistinguishable from a measured
zero -- and a zero is what a caller averages into an aggregate or compares to a
floor. Callers should treat a non-zero exit as void data, not as a score.

The document is opened and recomputed headless; the scored shape is the
PartDesign Body, else the first visible solid. IoU is computed by per-XY-column
Z-interval ray casting (see ``iou_math.py``): exact along Z, discretized only in
XY. Volume alone is not enough -- equal volume != equal shape.

OCC booleans (the direct way to get IoU) silently return an EMPTY shape on some
valid candidates -- `cut` gives back the whole candidate while `common` gives
nothing, i.e. OCC decides two overlapping solids do not intersect. FreeCAD's
mesh booleans hard-crash the process on the same inputs. Cross-checked on a
candidate where booleans DO work: boolean 0.9230 vs ray-cast 0.9257, a 0.3%
difference.
"""

import contextlib
import io
import os
import runpy
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "iou_core.py")


def die(reason):
    """Report an unmeasurable run: stderr only, non-zero exit, no number."""
    print(f"# {reason}", file=sys.stderr)
    raise SystemExit(2)


def candidate(doc):
    """The shape to score: the PartDesign Body, else the first visible solid."""
    shapes = [o.Shape for o in doc.Objects
              if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
    if not shapes:
        shapes = [o.Shape for o in doc.Objects
                  if getattr(o, "Shape", None) is not None and not o.Shape.isNull()
                  and o.Shape.Solids and getattr(o, "Visibility", False)]
    return shapes[0] if shapes else None


def main():
    if len(sys.argv) != 3:
        die("usage: score.py MODEL.FCStd REFERENCE_MESH")
    model, mesh = sys.argv[1:]
    for path in (model, mesh):
        if not os.path.isfile(path):
            die(f"not found: {path}")

    import FreeCAD

    # FreeCAD and iou_core print progress on stdout; keep it for the number only.
    out = io.StringIO()
    fd, brep = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        with contextlib.redirect_stdout(out):
            doc = FreeCAD.openDocument(model)
            doc.recompute()
            shape = candidate(doc)
            if shape is None:
                die("no solid in the model")
            shape.exportBrep(brep)
            sys.path.insert(0, HERE)
            sys.argv = ["iou_core", brep, mesh]
            runpy.run_path(CORE, run_name="iou_core")
    finally:
        Path(brep).unlink(missing_ok=True)
    if "IOU " not in out.getvalue():
        die(f"IoU failed: {out.getvalue()[-300:]}")
    print(out.getvalue().split("IOU ")[-1].split()[0])


main()
