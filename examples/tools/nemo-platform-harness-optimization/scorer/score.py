# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Score a CAD reconstruction by IoU against the reference mesh.

Usage::

    python3 score.py [DocName] [reference_mesh.obj]

Output contract:

* success -> one number in ``0.0`` - ``1.0`` on stdout, exit 0
* failure -> nothing on stdout, a ``# <reason>`` line on stderr, exit 2

A failure prints no number on purpose. An earlier revision printed ``0.0`` on
both paths, which makes "could not measure" indistinguishable from a measured
zero -- and a zero is what a caller averages into an aggregate or compares to a
floor. Callers should treat a non-zero exit as void data, not as a score.

Environment:

* ``FREECAD_BIN`` -- FreeCAD executable for the headless scoring pass
  (default: the macOS app bundle, or ``freecadcmd`` / ``FreeCADCmd`` on PATH)
* ``FREECAD_RPC`` -- XML-RPC endpoint of the live FreeCAD session
  (default: ``http://127.0.0.1:9875``)

IoU is computed by per-XY-column Z-interval ray casting (see ``iou_math.py``):
exact along Z, discretized only in XY. Volume alone is not enough -- equal
volume != equal shape.

Two things forced this design:

* OCC booleans (the direct way to get IoU) silently return an EMPTY shape on
  some valid candidates -- `cut` gives back the whole candidate while `common`
  gives nothing, i.e. OCC decides two overlapping solids do not intersect.
  FreeCAD's mesh booleans hard-crash the process on the same inputs.
  Cross-checked on a candidate where booleans DO work: boolean 0.9230 vs
  ray-cast 0.9257, a 0.3% difference.
* freecad-mcp caps any GUI-thread dispatch at 90s, which mesh->solid conversion
  plus booleans routinely exceeds. So the scoring runs in a HEADLESS FreeCAD;
  over RPC we only export the candidate solid to BREP, which is cheap.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import xmlrpc.client

HERE = os.path.dirname(os.path.abspath(__file__))
# Reference meshes live outside the agent directory: the agent spec fileset is
# capped at 900,000 bytes. FreeCAD reads them straight from disk, so they never
# need to be staged with the agent.
DEFAULT_MESH = os.path.join(os.path.dirname(HERE), "meshes", "reference_mug.obj")
CORE = os.path.join(HERE, "iou_core.py")
RPC = os.environ.get("FREECAD_RPC", "http://127.0.0.1:9875")

MACOS_FREECAD = "/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"


def die(reason):
    """Report an unmeasurable run: stderr only, non-zero exit, no number."""
    print(f"# {reason}", file=sys.stderr)
    raise SystemExit(2)


def find_freecad():
    """Resolve the FreeCAD executable, or exit with an actionable message."""
    override = os.environ.get("FREECAD_BIN")
    if override:
        resolved = shutil.which(override) or (
            override if os.path.isfile(override) else None)
        if resolved:
            return resolved
        die(f"FREECAD_BIN={override!r} is not an executable file")
    if sys.platform == "darwin" and os.path.isfile(MACOS_FREECAD):
        return MACOS_FREECAD
    for name in ("freecadcmd", "FreeCADCmd", "freecad", "FreeCAD"):
        found = shutil.which(name)
        if found:
            return found
    die("no FreeCAD executable found; set FREECAD_BIN to the FreeCAD binary "
        f"(macOS default: {MACOS_FREECAD}; Linux: freecadcmd on PATH)")


def export_snippet(doc, brep):
    return f"""
import FreeCAD, Part
ok = False
if {doc!r} in FreeCAD.listDocuments():
    d = FreeCAD.getDocument({doc!r})
    shapes = [o.Shape for o in d.Objects
              if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
    if not shapes:
        shapes = [o.Shape for o in d.Objects
                  if getattr(o, "Shape", None) is not None and not o.Shape.isNull()
                  and o.Shape.Solids and o.ViewObject and o.ViewObject.Visibility]
    if shapes:
        shapes[0].exportBrep({brep!r})
        ok = True
print("EXPORTED", ok)
"""


def main():
    doc = sys.argv[1] if len(sys.argv) > 1 else "EvalMug"
    mesh = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MESH
    if not os.path.isfile(mesh):
        die(f"reference mesh not found: {mesh}; pass one as argv[2]")

    freecad = find_freecad()
    # A fixed /tmp path would make two concurrent runs overwrite each other's
    # candidate, silently scoring one against the other's geometry.
    fd, brep = tempfile.mkstemp(prefix="cad_eval_candidate_", suffix=".brep")
    os.close(fd)
    try:
        try:
            res = xmlrpc.client.ServerProxy(RPC).execute_code(
                export_snippet(doc, brep))
        except Exception as exc:  # FreeCAD down, or RPC bridge not listening
            die(f"FreeCAD RPC at {RPC} unreachable: {exc}")
        if not res.get("success"):
            die(f"export failed: {res.get('code') or res.get('error')}")
        if "EXPORTED True" not in res["message"]:
            die("no visible solid in document")

        # FreeCAD -c reads stdin as an interactive console, so multi-line
        # blocks need blank-line terminators. exec() of a file sidesteps that
        # entirely; the sys.path insert lets iou_core find iou_math.
        script = (f"import sys; sys.path.insert(0, {HERE!r}); "
                  f"sys.argv = ['iou_core', {brep!r}, {mesh!r}]; "
                  f"exec(open({CORE!r}).read())\n")
        out = subprocess.run([freecad, "-c"], input=script,
                             capture_output=True, text=True)
        if "IOU " not in out.stdout:
            die(f"headless IoU failed: {out.stdout[-300:]} {out.stderr[-300:]}")
        print(out.stdout.split("IOU ")[-1].split()[0])
    finally:
        Path(brep).unlink(missing_ok=True)


main()
