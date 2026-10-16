# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Targeted negative controls: each task's reference solution, broken one way.

    SOLUTION=... OUT=dir freecadcmd make_negatives.py

visible.FCStd:  every feature and sketch left visible       -> fails single-visible-object
broken.FCStd:   the last feature's profile removed, saved     -> fails recomputes-after-reopen
                without rebuilding (the stored shape still looks right)
scripted.FCStd: the solution's solid as a scripted shape     -> fails native-feature-tree
                under the Body (BaseFeature), plus one small sketch-driven
                Pocket, so only the scripted base fails the check

The proof table in evals/README.md also lists controls taken from real agent runs
(slices, one-dimension, no-branch); those models are not shipped.
"""
import os

import FreeCAD as App
import Part
import Sketcher

out = os.environ["OUT"]


def solution():
    doc = App.openDocument(os.environ["SOLUTION"])
    doc.recompute()
    return doc, next(o for o in doc.Objects if o.TypeId == "PartDesign::Body")


doc, body = solution()
for obj in doc.Objects:
    obj.Visibility = True
doc.saveAs(f"{out}/visible.FCStd")
App.closeDocument(doc.Name)

doc, body = solution()
body.Tip.Profile = None
doc.saveAs(f"{out}/broken.FCStd")
App.closeDocument(doc.Name)

doc, body = solution()
solid = body.Shape.copy()
App.closeDocument(doc.Name)
doc = App.newDocument("Scripted")
base = doc.addObject("Part::Feature", "Scripted")
base.Shape = solid
body = doc.addObject("PartDesign::Body", "Body")
body.BaseFeature = base
doc.recompute()
# A small pocket straight down into the highest point of the part: a real sketch feature.
top = max(solid.Vertexes, key=lambda v: v.Point.z).Point
r = 0.02 * solid.BoundBox.DiagonalLength
sketch = body.newObject("Sketcher::SketchObject", "Sketch")
sketch.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]  # XY plane
sketch.MapMode = "FlatFace"
sketch.AttachmentOffset = App.Placement(App.Vector(0, 0, top.z), App.Rotation())
sketch.addGeometry(Part.Circle(App.Vector(top.x, top.y, 0), App.Vector(0, 0, 1), r))
sketch.renameConstraint(sketch.addConstraint(Sketcher.Constraint("Radius", 0, r)), "Radius")
pocket = body.newObject("PartDesign::Pocket", "Pocket")
pocket.Profile = sketch
pocket.Length = r
doc.recompute()
for obj in doc.Objects:
    obj.Visibility = obj is body
doc.saveAs(f"{out}/scripted.FCStd")
print("negatives written to", out)
