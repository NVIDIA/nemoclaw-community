# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Write SRC as an OBJ mesh at DST. Run with: SRC=... DST=... freecadcmd fc.py

SRC is a mesh (OBJ or STL) or a FreeCAD model (.FCStd). A model is reopened as the scorer
does (evals/verifier/check_model.py, load: every object touched, recomputed; keep the two
alike) and its single PartDesign Body is tessellated, finely enough to see, relative to the
part's size; with no Body, the visible top-level shapes are. Writes nothing when there is
nothing to show.
"""
import os

import FreeCAD
import Mesh
import MeshPart
import Part

src, dst = os.environ['SRC'], os.environ['DST']
if src.lower().endswith('.fcstd'):
    doc = FreeCAD.openDocument(src)
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    bodies = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body']
    shapes = [bodies[0].Shape] if len(bodies) == 1 else [
        o.Shape for o in doc.Objects if not o.InList and getattr(o, 'Visibility', False)
        and hasattr(o, 'Shape') and not o.Shape.isNull()]
    if not shapes:
        raise RuntimeError('no shape to show')
    shape = Part.makeCompound(shapes)
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=max(1e-3 * shape.BoundBox.DiagonalLength, 0.01),
                                  AngularDeflection=0.15, Relative=False)
else:
    mesh = Mesh.Mesh(src)
if not mesh.CountFacets:
    raise RuntimeError('no triangles')
mesh.write(dst)
