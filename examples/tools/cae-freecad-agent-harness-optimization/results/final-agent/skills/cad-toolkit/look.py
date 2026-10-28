# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render the mesh and your saved model to one small PNG, then LOOK at it with read_file.

    python3 /agent/skills/cad-toolkit/look.py                 # /app/model.FCStd vs /app/reference.obj
    python3 /agent/skills/cad-toolkit/look.py --cut y --views front,iso   # half section: walls, cavities

Takes ~5-10 s. Top row: the mesh (blue, the target). Bottom row: your model (orange), each
column the SAME camera, so size, position and orientation compare directly. When
/app/frame.json exists both are drawn in the part's local frame (measure.py):
front = looking along local +y (shows x-z), right = along local -x (shows y-z),
top = looking down local z (shows x-y), bottom = looking up local z. Then: read_file /app/look.png.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# Shared with the agent's middleware: run deadline and whether a valid model is saved.
STATE_FILE = os.path.join(tempfile.gettempdir(), 'cad_guard_state.json')
LOOKS_FILE = os.path.join(tempfile.gettempdir(), 'cad_looks')


def gate(model, mesh_only):
    """Look only where it can decide the next fix: a valid model saved, time left to act."""
    import time
    st = {}
    try:
        st = json.load(open(STATE_FILE))
    except (OSError, ValueError):
        pass  # no guard running (e.g. a manual test): only the file checks below apply
    try:
        looks = int(open(LOOKS_FILE).read().strip() or 0)
    except (OSError, ValueError):
        looks = 0
    try:  # saved after the guard last checked it (same command): not judged yet, allow
        fresh = os.path.getmtime(model) > os.path.getmtime(STATE_FILE)
    except OSError:
        fresh = False
    if not os.path.exists(model) or (st and not st.get('valid') and not fresh):
        return ('look.py: no valid model is saved yet, so there is nothing to compare. Do not '
                'look now: build the main body (one pad, revolve or loft from your measurements), '
                'save it with K.finish, then run look.py.')
    if st:
        left = st['deadline'] - time.time()
        if left < st.get('look_min_left', 90):
            return (f'look.py: only {int(left)} s left, too little to act on a look. Keep the '
                    'saved valid model, run verify.py and report.')
        if looks >= st.get('max_looks', 2):
            return (f'look.py: {looks} looks done already. Use the numbers now: verify.py '
                    '(missing/extra material location) and sections.py --model.')
    return ''


def count_look():
    try:
        n = int(open(LOOKS_FILE).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    try:
        with open(LOOKS_FILE, 'w') as fh:
            fh.write(str(n + 1))
    except OSError:
        pass
METHODS = {'iso': 'viewIsometric', 'front': 'viewFront', 'rear': 'viewRear', 'right': 'viewRight',
           'left': 'viewLeft', 'top': 'viewTop', 'bottom': 'viewBottom'}


def outer():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('model', nargs='?', default='/app/model.FCStd')
    ap.add_argument('mesh', nargs='?', default='/app/reference.obj')
    ap.add_argument('--mesh-only', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--views', default='iso,front,right,top,bottom')
    ap.add_argument('--out', default='/app/look.png')
    ap.add_argument('--size', type=int, default=280, help='panel width in px (height 3/4 of it)')
    ap.add_argument('--frame', default='/app/frame.json')
    ap.add_argument('--cut', choices=['x', 'y', 'z'], help='cut both in half across this local axis '
                    '(keep the + half) to show cavities, walls and floors')
    a = ap.parse_args()
    bad = [v for v in a.views.split(',') if v not in METHODS]
    if bad:
        sys.exit(f'unknown view(s) {bad}; use {sorted(METHODS)}')
    why = gate(a.model, a.mesh_only)
    if why:
        print(why)
        return
    a.mesh_only = False  # the point of a look is the model beside the mesh
    a.log = a.out + '.log'
    if os.path.exists(a.log):
        os.remove(a.log)
    env = dict(os.environ, LOOK_INNER=json.dumps(vars(a)))
    cmd = ['xvfb-run', '-a', '-s', '-screen 0 1280x1024x24', 'freecadcmd', os.path.abspath(__file__)]
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        sys.exit('look.py: render timed out after 45 s (skip looking; use verify.py numbers)')
    out = (p.stdout + p.stderr).replace('\r', '\n')
    if os.path.exists(a.log):  # the GUI swallows print(): the inner process logs to a file
        out = open(a.log).read() + out
        os.remove(a.log)
    lines = [ln for ln in out.splitlines() if ln.startswith('look:')]
    print('\n'.join(ln[5:].strip() for ln in lines) or out[-1500:])
    if os.path.exists(a.out) and any('saved' in ln for ln in lines):
        what = ('the mesh only' if a.mesh_only else
                'top row mesh = target, bottom row = your model, same cameras')
        count_look()
        print(f'NOW: read_file {a.out}  ({what})')
    else:
        sys.exit('look.py: no image written')


def inner(a):
    logf = open(a['log'], 'a')

    def print(*args):  # noqa: A001
        logf.write(' '.join(str(x) for x in args) + '\n')
        logf.flush()

    import FreeCAD as App
    import FreeCADGui as Gui
    import Mesh
    import Part
    Gui.showMainWindow()
    from PySide import QtGui
    app = QtGui.QApplication.instance()

    def settle():
        for _ in range(10):
            app.processEvents()

    M = None
    if a['frame'] and os.path.exists(a['frame']):
        fr = json.load(open(a['frame']))
        R, o = fr['R'], fr['origin']
        # local = R (world - origin): rows of R are the local axes
        t = [-(R[i][0] * o[0] + R[i][1] * o[1] + R[i][2] * o[2]) for i in range(3)]
        M = App.Matrix(R[0][0], R[0][1], R[0][2], t[0],
                       R[1][0], R[1][1], R[1][2], t[1],
                       R[2][0], R[2][1], R[2][2], t[2], 0, 0, 0, 1)
    doc = App.newDocument('LookTmp')
    mesh = Mesh.Mesh(os.path.abspath(a['mesh']))
    if M is not None:
        mesh.transform(M)
    mobj = doc.addObject('Mesh::Feature', 'Target')
    mobj.Mesh = mesh
    sobj, info = None, ''
    mb = mesh.BoundBox
    info = f'mesh  local bbox x[{mb.XMin:.3g},{mb.XMax:.3g}] y[{mb.YMin:.3g},{mb.YMax:.3g}] z[{mb.ZMin:.3g},{mb.ZMax:.3g}]'
    print('look:', info)
    if not a['mesh_only']:
        src = App.openDocument(os.path.abspath(a['model']))
        for ob in src.Objects:
            ob.touch()
        src.recompute()
        bodies = [ob for ob in src.Objects if ob.TypeId == 'PartDesign::Body']
        shp = bodies[0].Shape.copy() if bodies else None
        App.closeDocument(src.Name)
        App.setActiveDocument(doc.Name)
        if shp is None or shp.isNull():
            print('look: model has no Body shape: rendering the mesh only')
        else:
            if M is not None:
                try:
                    shp = shp.transformed(M)
                except Exception:  # a mirrored frame is not a rigid move
                    shp = shp.transformGeometry(M)
            sobj = doc.addObject('Part::Feature', 'Model')
            sobj.Shape = shp
            sb = shp.BoundBox
            print(f'look: model local bbox x[{sb.XMin:.3g},{sb.XMax:.3g}] y[{sb.YMin:.3g},{sb.YMax:.3g}] '
                  f'z[{sb.ZMin:.3g},{sb.ZMax:.3g}]  solids {len(shp.Solids)}')
            print(f'look: volume model/mesh {shp.Volume / max(mesh.Volume, 1e-12):.3f}  (far from 1: '
                  'material missing or extra; the image shows where)')
    if a.get('cut'):
        import Part
        k = 'xyz'.index(a['cut'])
        bb = mobj.Mesh.BoundBox
        mid = [(bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2, (bb.ZMin + bb.ZMax) / 2][k]
        nrm = App.Vector(*[1 if i == k else 0 for i in range(3)])
        base = App.Vector(*[mid if i == k else 0 for i in range(3)])
        m2 = mobj.Mesh.copy()
        m2.trimByPlane(base, -nrm)  # keep the + side
        mobj.Mesh = m2
        if sobj:
            big = 10 * max(bb.XLength, bb.YLength, bb.ZLength, 1)
            lo = App.Vector(*[mid if i == k else -big for i in range(3)])
            box = Part.makeBox(2 * big if k else big, 2 * big if k != 1 else big, 2 * big if k != 2 else big, lo)
            sobj.Shape = sobj.Shape.common(box)
        print(f'look: cut at local {a["cut"]}={mid:.3g}, + half kept (cut faces are the open side)')
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)
    gd = Gui.ActiveDocument
    gd.getObject('Target').ShapeColor = (0.35, 0.55, 0.85)
    if sobj:
        vo = gd.getObject('Model')
        vo.ShapeColor, vo.DisplayMode = (0.95, 0.55, 0.15), 'Shaded'
    view = gd.ActiveView
    view.setAnimationEnabled(False)
    W = int(a['size'])
    H = W * 3 // 4
    views = a['views'].split(',')
    rows = [('mesh (target)', 'Target')] + ([('your model', 'Model')] if sobj else [])
    panels = {}
    for vname in views:
        for ob in doc.Objects:
            gd.getObject(ob.Name).Visibility = True
        getattr(view, METHODS[vname])()
        settle()
        view.fitAll()  # one camera for both rows, fitted to both
        settle()
        for r, (_, name) in enumerate(rows):
            for ob in doc.Objects:
                gd.getObject(ob.Name).Visibility = (ob.Name == name)
            settle()
            path = f'/tmp/look_{r}_{vname}.png'
            view.saveImage(path, W, H, 'White')
            panels[(r, vname)] = path
    out = QtGui.QImage(W * len(views), H * len(rows), QtGui.QImage.Format_RGB32)
    out.fill(QtGui.QColor('white'))
    pt = QtGui.QPainter(out)
    pt.setFont(QtGui.QFont('Sans', max(9, W // 28)))
    for r, (label, _) in enumerate(rows):
        for c, vname in enumerate(views):
            pt.drawImage(c * W, r * H, QtGui.QImage(panels[(r, vname)]))
            pt.drawText(c * W + 6, r * H + W // 18, f'{label}: {vname}')
    pt.setPen(QtGui.QColor('gray'))
    for c in range(1, len(views)):
        pt.drawLine(c * W, 0, c * W, H * len(rows))
    for r in range(1, len(rows)):
        pt.drawLine(0, r * H, W * len(views), r * H)
    pt.end()
    out.save(a['out'])
    frame = 'local frame' if M is not None else 'world frame (no frame.json)'
    print(f'look: saved {a["out"]} ({W * len(views)}x{H * len(rows)}, {frame})')
    logf.close()


if os.environ.get('LOOK_INNER'):
    try:
        inner(json.loads(os.environ['LOOK_INNER']))
    except Exception as e:  # report, never hang
        with open(json.loads(os.environ['LOOK_INNER'])['log'], 'a') as f:
            f.write(f'look: ERROR {type(e).__name__}: {str(e)[:300]}\n')
    sys.stdout.flush()
    os._exit(0)
elif __name__ == '__main__':
    outer()
