# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Targeted negative controls: each task's reference solution, broken one way.

    SOLUTION=... OUT=dir freecadcmd make_negatives.py

visible.FCStd:  every feature and sketch left visible       -> fails single-visible-object
broken.FCStd:   the last feature's profile removed, saved     -> fails recomputes-after-reopen
                without rebuilding (the stored shape still looks right)
scripted.FCStd: the solution's solid as a scripted shape     -> fails native-feature-tree
                under the Body (BaseFeature)

part-1-reconstruction/slices.FCStd is not generated: it is a real agent run (32 stacked
pads, IoU 0.91) that passes every other check and fails compact-model.
<task>/one-dimension.FCStd is not generated either: a real run of the final agent (4 ruled
lofts, every section height a fraction of one Params.Length) that passes every other
check and fails independent-dimensions.
"""
import os

import FreeCAD as App

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
for obj in doc.Objects:
    obj.Visibility = obj is body
doc.saveAs(f"{out}/scripted.FCStd")
print("negatives written to", out)
