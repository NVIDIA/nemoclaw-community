# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Grade a saved FreeCAD document. Run with: freecadcmd check_model.py (env MODEL, MESH,
REF_FACES: the reference solution's face count, for compact-model).

Writes one ``<check-id>\\tPASS|FAIL`` row per check to /logs/verifier/results.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile

import FreeCAD

RESULTS = "/logs/verifier/results"
IOU_MIN = 0.90
# no-missing-feature: the largest connected region of the reference the model leaves out
# (iou_math.largest_missing_fraction) may be at most this fraction of the reference volume.
MISSING_MAX = 0.012
# Features that build geometry from sketches.
SKETCH_FEATURES = {
    "PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft", "PartDesign::AdditivePipe",
    "PartDesign::SubtractivePipe", "PartDesign::AdditiveHelix", "PartDesign::SubtractiveHelix",
}
# A shape assigned by a script rather than built by a feature, including a Body's
# BaseFeature (a shape brought in from outside the tree).
WRAPPERS = {"PartDesign::Feature", "PartDesign::FeaturePython", "Part::Feature", "Part::FeaturePython",
            "PartDesign::FeatureBase"}
DRIVING = {"Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"}
# Datum helpers that carry no model geometry.
ORIGIN = {"App::Origin", "App::Line", "App::Plane", "App::Point"}


def row(check, ok):
    with open(RESULTS, "a") as f:
        f.write(f"{check}\t{'PASS' if ok else 'FAIL'}\n")
    print(check, "PASS" if ok else "FAIL")


def clean(shape):
    """FreeCAD's full shape check, including self-intersections: a loft that folds
    through itself can pass isValid() and still overlap the mesh closely."""
    try:
        shape.check(True)
        return True
    except Exception as exc:  # check() raises with the list of faults
        print("shape check failed:", str(exc).splitlines()[0])
        return False


def fingerprint(body):
    shape = body.Shape
    box = shape.BoundBox
    return (round(shape.Volume, 6), round(box.XLength, 6), round(box.YLength, 6), round(box.ZLength, 6))


def iou(body):
    brep = tempfile.mktemp(suffix=".brep")
    body.Shape.exportBrep(brep)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.argv = ["iou_core", brep, os.environ["MESH"]]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "iou_core.py")).read(),
             {"__name__": "__main__"})
    fid = re.search(r"IOU ([0-9.]+)", out.getvalue())
    gap = re.search(r"MISSING ([0-9.]+)", out.getvalue())
    return (float(fid.group(1)) if fid else 0.0), (float(gap.group(1)) if gap else 1.0)


def drivers(doc):
    """Named dimensions: named driving sketch constraints, and numeric properties
    that expressions in the document reference (e.g. ``Parameters.Height``)."""
    for obj in doc.Objects:
        if obj.TypeId == "Sketcher::SketchObject":
            for c in obj.Constraints:
                if c.Name and c.Type in DRIVING and c.Driving:
                    yield ("constraint", obj, c.Name)
    seen = set()
    for obj in doc.Objects:
        for _, expression in getattr(obj, "ExpressionEngine", []) or []:
            for name, prop in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", expression):
                target = doc.getObject(name) or next(iter(doc.getObjectsByLabel(name)), None)
                if target is None or (target.Name, prop) in seen:
                    continue
                seen.add((target.Name, prop))
                if isinstance(getattr(target, prop, None), (int, float, FreeCAD.Units.Quantity)):
                    yield ("property", target, prop)


# A named dimension moves the part when a 10% change leaves one clean solid whose
# bounding-box length changes by at least this fraction.
SIZE_CHANGE_MIN = 0.01


def response(doc, body, kind, obj, name):
    """Change one named dimension by 10%, rebuild, and return (clean, relative change of
    volume, X, Y and Z length). The value is restored."""
    before = fingerprint(body)
    if kind == "constraint":
        value = obj.getDatum(name)
        put, restore = (lambda v: obj.setDatum(name, v)), (lambda: obj.setDatum(name, value))
    elif obj.TypeId == "Spreadsheet::Sheet":
        # Through the cell, which takes any number, and restored to its exact contents, so a
        # formula such as =Length/2 stays a formula.
        cell, value = obj.getCellFromAlias(name), getattr(obj, name)
        contents = obj.getContents(cell)
        put, restore = (lambda v: obj.set(cell, str(v))), (lambda: obj.set(cell, contents))
    else:
        value = getattr(obj, name)
        put, restore = (lambda v: setattr(obj, name, v)), (lambda: setattr(obj, name, value))
    try:
        put(value * 1.1)
        doc.recompute()
        shape = body.Shape
        if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
            return False, (0.0,) * len(before)
        delta = tuple((a - b) / b if b else 0.0 for a, b in zip(fingerprint(body), before))
        # The full shape check is costly; it only matters when the part moved enough to count.
        if max(abs(d) for d in delta) < INTENT_CHANGE_MIN:
            return True, delta
        return (True, delta) if clean(shape) else (False, (0.0,) * len(before))
    finally:
        restore()
        doc.recompute()


def moves_geometry(change):
    ok, delta = change
    return ok and any(abs(d) >= SIZE_CHANGE_MIN for d in delta[1:])


# Design intent: two named dimensions that each move the volume or a bounding-box length
# by INTENT_CHANGE_MIN and change the part differently (cosine of their changes below
# INTENT_COSINE_MAX in magnitude: opposite changes are the same stretch), compared with
# each other, so any part and orientation works.
INTENT_CHANGE_MIN = 0.005
INTENT_COSINE_MAX = 0.9


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return dot / norm if norm else 1.0


# A designer's model has about as many faces as the part has surfaces. Stacked slices
# and faceted profiles add faces with every band and polygon segment, so a model may
# have at most this many times the faces of the task's reference solution (REF_FACES).
FACES_RATIO_MAX = 10


def compact(body):
    reference = int(os.environ.get("REF_FACES", "0"))
    faces = len(body.Shape.Faces)
    print("compact-model faces", faces, "reference", reference, "limit", FACES_RATIO_MAX * reference)
    return reference > 0 and faces <= FACES_RATIO_MAX * reference


def single_visible_object(doc, body):
    """Exactly one visible model: every visible object with geometry is the Body or
    its tip feature (how PartDesign shows a Body). Origin axes and planes are ignored."""
    if body is None:
        return False
    shown = [o for o in doc.Objects
             if getattr(o, "Visibility", False) and o.TypeId not in ORIGIN
             and hasattr(o, "Shape") and not o.Shape.isNull()]
    return bool(shown) and all(o in (body, body.Tip) for o in shown)


def main():
    open(RESULTS, "w").close()
    doc = FreeCAD.openDocument(os.environ["MODEL"])
    # Rebuild every feature from its inputs, as reopening in FreeCAD and editing would: a
    # plain recompute only rebuilds objects saved as touched. A feature whose rebuild fails
    # keeps its stored shape, so the checks below may still see that shape; this check
    # fails the run.
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    broken = [o.Name for o in doc.Objects if not o.isValid()]
    if broken:
        print("invalid after recompute:", broken)
    row("recomputes-after-reopen", bool(doc.Objects) and not broken)
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    body = bodies[0] if len(bodies) == 1 else None
    solid = body is not None and not body.Shape.isNull() and body.Shape.isValid() \
        and len(body.Shape.Solids) == 1 and clean(body.Shape)
    row("single-valid-solid", solid)

    features = [o for o in (body.Group if body else []) if o.TypeId.startswith(("PartDesign::", "Part::"))]
    sketch_driven = [o for o in features if o.TypeId in SKETCH_FEATURES]
    wrappers = [o for o in features if o.TypeId in WRAPPERS]
    row("native-feature-tree", bool(sketch_driven) and not wrappers)

    fidelity, missing = iou(body) if solid else (0.0, 1.0)
    if solid:
        print("mesh-fidelity IoU", round(fidelity, 4))
        print("no-missing-feature largest uncovered region", round(missing, 4), "limit", MISSING_MAX)
    else:
        print("mesh-fidelity not measured: no valid solid")
    row("mesh-fidelity", fidelity >= IOU_MIN)
    row("no-missing-feature", missing <= MISSING_MAX)

    driven, intent = False, False
    moving = []  # (name, relative change) of each dimension that moves the part
    if solid:
        for candidate in drivers(doc):
            try:
                change = response(doc, body, *candidate)
            except Exception as exc:  # a driver that cannot be changed does not count
                print("driver", candidate[2], "failed:", exc)
                continue
            print("driver", candidate[1].Name, candidate[2], "clean", change[0],
                  "dV dX dY dZ", [round(d, 4) for d in change[1]])
            driven = driven or moves_geometry(change)
            if change[0] and max(abs(d) for d in change[1]) >= INTENT_CHANGE_MIN:
                for name, other in moving:
                    if abs(cosine(change[1], other)) < INTENT_COSINE_MAX:
                        print("independent dimensions:", name, "and", candidate[2])
                        intent = True
                moving.append((candidate[2], change[1]))
            if driven and intent:
                break
    row("named-dimension-drives-geometry", driven)
    row("independent-dimensions", intent)
    row("single-visible-object", single_visible_object(doc, body))
    row("compact-model", solid and compact(body))
    log_complexity(body)


def log_complexity(body):
    """Not a check: record how complex the model is, for the results tables."""
    group = body.Group if body else []
    sketches = [o for o in group if o.TypeId == "Sketcher::SketchObject"]
    stats = {
        "features": len([o for o in group if o.TypeId in SKETCH_FEATURES]),
        "sketches": len(sketches),
        "sketch_geometry": sum(len(o.Geometry) for o in sketches),
        "faces": len(body.Shape.Faces) if body and not body.Shape.isNull() else 0,
    }
    print("complexity", json.dumps(stats))
    with open(os.path.join(os.path.dirname(RESULTS), "complexity.json"), "w") as f:
        json.dump(stats, f)


main()
