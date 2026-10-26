# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Grade a saved FreeCAD document. Run with: freecadcmd check_model.py (env MODEL, MESH,
REF_FACES: the reference solution's face count, for compact-model).

Writes one ``<check-id>\\tPASS|FAIL`` row per check to /logs/verifier/results, and the
IoU and complexity counts to /logs/verifier/metrics.json.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time

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
    # The exact box: BoundBox includes spline control points, so on a lofted part a
    # dimension could seem to move the part when its surface does not move.
    box = shape.optimalBoundingBox(False)
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


# A named dimension moves the part when a 10% change leaves one clean solid whose volume
# or a bounding-box length changes by at least this fraction (ETHOS: a hole size moves the
# volume, not the box).
SIZE_CHANGE_MIN = 0.01


def response(doc, body, kind, obj, name):
    """Change one named dimension by 10% (-10% if the sketch solver rejects +10%), rebuild,
    and return ((clean, relative change of volume, X, Y and Z length), restored): the value
    is put back, and ``restored`` says whether the part came back with it."""
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
    for factor in (1.1, 0.9):
        try:
            put(value * factor)
            break
        except Exception:  # e.g. an ellipse's minor axis may not exceed its major
            if factor == 0.9:
                raise
    try:
        doc.recompute()
        shape = body.Shape
        if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
            change = False, (0.0,) * len(before)
        else:
            delta = tuple((a - b) / b if b else 0.0 for a, b in zip(fingerprint(body), before))
            # The full shape check is costly; it only matters when the part moved enough to count.
            if max(abs(d) for d in delta) < INTENT_CHANGE_MIN or clean(shape):
                change = True, delta
            else:
                change = False, (0.0,) * len(before)
    finally:
        restore()
        doc.recompute()
    restored = all(abs(a - b) <= 1e-3 * max(abs(b), 1.0) for a, b in zip(fingerprint(body), before))
    return change, restored


def moves_geometry(change):
    ok, delta = change
    return ok and any(abs(d) >= SIZE_CHANGE_MIN for d in delta)


# Design intent: two named dimensions that each move the volume or a bounding-box length
# by INTENT_CHANGE_MIN and change the part differently (cosine of their changes below
# INTENT_COSINE_MAX in magnitude: opposite changes are the same stretch), compared with
# each other, so any part and orientation works.
INTENT_CHANGE_MIN = 0.005
INTENT_COSINE_MAX = 0.9
# The dimension probes rebuild the model each time; on a model slow to rebuild they stop
# after this long, so the run is graded on the dimensions probed instead of not at all.
PROBE_SECONDS = 300


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


def load():
    """Open the saved model and rebuild every feature from its inputs, as reopening in
    FreeCAD and editing would: a plain recompute only rebuilds objects saved as touched."""
    doc = FreeCAD.openDocument(os.environ["MODEL"])
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    return doc, bodies[0] if len(bodies) == 1 else None


def main():
    open(RESULTS, "w").close()
    doc, body = load()
    # A feature whose rebuild fails keeps its stored shape, so the checks below may still
    # see that shape; this check fails the run.
    broken = [o.Name for o in doc.Objects if not o.isValid()]
    if broken:
        print("invalid after recompute:", broken)
    row("recomputes-after-reopen", bool(doc.Objects) and not broken)
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

    # Graded on the part as saved, before any dimension is changed, and written first: if a
    # probe below hangs, test.sh stops the verifier and these rows stand.
    row("single-visible-object", single_visible_object(doc, body))
    row("compact-model", solid and compact(body))
    log_metrics(body, fidelity if solid else None)

    driven, intent = False, False
    moving = []  # (name, relative change) of each dimension that moves the part
    if solid:
        saved = fingerprint(body)
        deadline = time.time() + PROBE_SECONDS
        for kind, owner, name in [(k, o.Name, n) for k, o, n in drivers(doc)]:
            if time.time() > deadline:
                print("dimension probes stopped after", PROBE_SECONDS, "s")
                break
            try:
                change, restored = response(doc, body, kind, doc.getObject(owner), name)
            except Exception as exc:  # a driver that cannot be changed does not count
                print("driver", name, "failed:", exc)
                change, restored = None, False
            if not restored:
                # A dimension that cannot be changed and put back is not one a designer can
                # edit; if the part moved, reopen, so the next one is measured on the part
                # as saved.
                if change and change[0]:
                    print("driver", owner, name, "does not restore the part: not counted")
                if fingerprint(body) != saved:
                    FreeCAD.closeDocument(doc.Name)
                    doc, body = load()
                continue
            print("driver", owner, name, "clean", change[0],
                  "dV dX dY dZ", [round(d, 4) for d in change[1]])
            driven = driven or moves_geometry(change)
            if change[0] and max(abs(d) for d in change[1]) >= INTENT_CHANGE_MIN:
                for earlier, other in moving:
                    if abs(cosine(change[1], other)) < INTENT_COSINE_MAX:
                        print("independent dimensions:", earlier, "and", name)
                        intent = True
                moving.append((name, change[1]))
            if driven and intent:
                break
    row("named-dimension-drives-geometry", driven)
    row("independent-dimensions", intent)


def log_metrics(body, fidelity):
    """Not a check: record the IoU (None: not measured) and how complex the model is, for
    the results tables."""
    group = body.Group if body else []
    sketches = [o for o in group if o.TypeId == "Sketcher::SketchObject"]
    stats = {
        "features": len([o for o in group if o.TypeId in SKETCH_FEATURES]),
        "sketches": len(sketches),
        "sketch_geometry": sum(len(o.Geometry) for o in sketches),
        "faces": len(body.Shape.Faces) if body and not body.Shape.isNull() else 0,
    }
    print("complexity", json.dumps(stats))
    with open(os.path.join(os.path.dirname(RESULTS), "metrics.json"), "w") as f:
        json.dump({"iou": fidelity, **stats}, f)


main()
