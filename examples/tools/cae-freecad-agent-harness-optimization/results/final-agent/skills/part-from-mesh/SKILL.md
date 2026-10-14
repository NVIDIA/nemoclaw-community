---
name: part-from-mesh
description: A tested routine that turns a triangle mesh of any single part (OBJ or STL) into an editable PartDesign body. Run three code blocks, then call one function until it prints DONE. Use it first for any mesh reconstruction.
---

# Part from mesh

The routine slices the mesh across a direction and links the outlines that continue
from slice to slice into chains. Each chain becomes a loft through sketched sections,
with a subtractive loft for any hole it carries. It tries candidate directions (the
three world axes, then the part's own principal axes) until one matches the mesh
closely, and keeps the best model. A `Params.Height` property drives every section's
height. It leaves one visible object, the Body. Every call finishes in under a minute.

This file is longer than 100 lines: read it with `read_file` and `limit: 400` so you
see all three blocks. The code exists only here; paste it into `execute_code`.

## Do exactly this

1. Run block 1, block 2 and block 3 below, in order, each as the `code` of one
   `execute_code` call, copied verbatim with no changes. Each checks itself and prints
   `block N of 3 loaded`; if it prints that the block is wrong, run it again, copied
   exactly. Code defined in one call stays available to the next.
2. Then call `execute_code` with exactly this one line, using the task's document name
   and mesh path as written in the task:

   ```python
   step("<document name>", "<mesh path>")
   ```

   It builds and measures the model, usually in one call, and prints `DONE`.
3. If it prints `Call step again with the same arguments.`, repeat that same one-line
   call, unchanged, until it prints `DONE`. Do nothing else in between.
4. If it prints `ERROR`, run blocks 1, 2 and 3 again, copied exactly, then call step
   again.
5. When it prints `DONE`, **you are done**: reply with your final report now, without
   calling any more tools. The model is finished and checked; inspecting, changing,
   re-running or deleting anything after DONE can only break it.

Never write your own version and never add code to the step call. Pass only `code`
(and `include_screenshot: false`) to `execute_code`; never pass `timeout`. Do not
delete documents or objects.


## Block 1

```python
import numpy as np
import FreeCAD as App, Part, Mesh

def area(l):
    return 0.5 * (np.dot(l[:, 0], np.roll(l[:, 1], -1)) - np.dot(l[:, 1], np.roll(l[:, 0], -1)))

def inside(p, l):
    x, y = l[:, 0], l[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cross = (y > p[1]) != (y2 > p[1])
    xs = x + (p[1] - y) * (x2 - x) / (y2 - y + 1e-30)
    return np.count_nonzero(cross & (p[0] < xs)) % 2 == 1

def fill(loops, gx, gy):
    res = np.zeros(gx.shape, bool)
    for l in loops:
        (xa, ya), (xb, yb) = np.roll(l, 1, axis=0).T[:, :, None, None], l.T[:, :, None, None]
        xs = xa + (gy - ya) * (xb - xa) / np.where(yb == ya, 1e-30, yb - ya)
        res ^= np.count_nonzero(((ya > gy) != (yb > gy)) & (gx < xs), axis=0) % 2 == 1
    return res

def fit_to_mesh(shape, m, n=80):
    # mean overlap of model and mesh cross-sections across each world axis (1 = identical)
    b = m.BoundBox
    lim = [(b.XMin, b.XMax), (b.YMin, b.YMax), (b.ZMin, b.ZMax)]
    vals = []
    for k in range(3):
        u, v = [i for i in range(3) if i != k]
        nv = App.Vector(*np.eye(3)[k])
        gx, gy = np.meshgrid(np.linspace(*lim[u], n), np.linspace(*lim[v], n))
        for f in (0.15, 0.35, 0.5, 0.65, 0.85):
            d = lim[k][0] + f * (lim[k][1] - lim[k][0])
            mesh_loops = []
            for L in m.crossSections([(nv * d, nv)])[0]:
                mesh_loops.append(np.array([[q[u], q[v]] for q in L]))
            model_loops = []
            for w in shape.slice(nv, d):
                model_loops.append(np.array([[q[u], q[v]] for q in w.discretize(200)]))
            a = fill(mesh_loops, gx, gy)
            c = fill(model_loops, gx, gy)
            if np.any(a | c):
                vals.append(np.count_nonzero(a & c) / np.count_nonzero(a | c))
    return float(np.mean(vals)) if vals else 0.0

def chains_along(m, axis, n):
    # slice across axis; an outline continues the chain whose last outline it overlaps most
    P = np.array([[p.x, p.y, p.z] for p in m.Points])
    c0 = P.mean(axis=0)
    e1 = np.cross(axis, [0, 0, 1] if abs(axis[2]) < 0.9 else [1, 0, 0])
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    t = (P - c0) @ axis
    lo, H = t.min(), t.max() - t.min()
    chains, live = [], []
    for i in range(n):
        h = lo + H * (0.004 + 0.992 * i / (n - 1))
        loops = []
        for L in m.crossSections([(App.Vector(*(c0 + axis * h)), App.Vector(*axis))])[0]:
            q = np.array([[p.x, p.y, p.z] for p in L]) - c0
            if len(q) >= 4:
                loops.append(np.c_[q @ e1, q @ e2])
        regions = []
        for l in sorted(loops, key=lambda l: -abs(area(l))):
            host = [r for r in regions if inside(l[0], r[0])]
            if not host:
                regions.append([l, None])
            elif host[0][1] is None:
                host[0][1] = l
        nxt = []
        for outline, hole in regions:
            lo2, hi2 = outline.min(axis=0), outline.max(axis=0)
            best, score = None, 0.25
            for c in live:
                a, b = c[-1][1].min(axis=0), c[-1][1].max(axis=0)
                inter = np.prod(np.clip(np.minimum(hi2, b) - np.maximum(lo2, a), 0, None))
                ov = inter / (np.prod(hi2 - lo2) + np.prod(b - a) - inter)
                if ov > score and all(c is not x for x in nxt):
                    best, score = c, ov
            if best is None:
                best = []
                chains.append(best)
            best.append((h - lo, outline, hole))
            nxt.append(best)
        live = nxt
    chains = [c for c in chains if len(c) >= 2]
    chains.sort(key=lambda c: -sum(abs(area(o)) for _, o, _ in c))
    rot = App.Rotation(App.Matrix(*e1, 0, *e2, 0, *axis, 0, 0, 0, 0, 1).transposed())
    return chains, App.Placement(App.Vector(*(c0 + axis * lo)), rot), H

# self-test on a small box: a wrongly copied block fails here instead of later
box = Mesh.createBox(10, 10, 10)
try:
    ok = abs(fit_to_mesh(Part.makeBox(10, 10, 10, App.Vector(-5, -5, -5)), box) - 1) < 0.05
    ok = ok and len(chains_along(box, np.array([0.0, 0.0, 1.0]), 6)[0]) == 1
except Exception:
    ok = False
print('block 1 of 3 loaded' if ok else 'block 1 is wrong: run block 1 again, copied exactly')
```

## Block 2

```python
import numpy as np
import FreeCAD as App, Part, Mesh

def resample(l, n=48):
    l = l if area(l) > 0 else l[::-1]
    closed = np.r_[l, l[:1]]
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
    t = np.linspace(0, s[-1], n, endpoint=False)
    p = np.c_[np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])]
    c = p.mean(axis=0)
    return np.roll(p, -int(np.argmin(np.abs(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])))), axis=0)

def align(items):
    # start each outline where it best matches the previous one
    out = [items[0]]
    for h, p in items[1:]:
        prev = out[-1][1] - out[-1][1].mean(axis=0)
        cur = p - p.mean(axis=0)
        errors = []
        for k in range(len(cur)):
            errors.append(((np.roll(cur, -k, axis=0) - prev) ** 2).sum())
        k = int(np.argmin(errors))
        out.append((h, np.roll(p, -k, axis=0)))
    return out

def build(doc, m, axis, n=60):
    # one loft per chain of outlines, a subtractive loft for its hole
    # Params.Height drives every section
    chains, place, H = chains_along(m, np.asarray(axis, float), n)
    body = doc.addObject('PartDesign::Body', 'Body')
    body.Placement = place
    par = doc.getObject('Params') or doc.addObject('App::FeaturePython', 'Params')
    if not hasattr(par, 'Height'):
        par.addProperty('App::PropertyLength', 'Height', 'Dimensions')
    par.Height = H
    xy = [f for f in body.Origin.OriginFeatures if f.Role == 'XY_Plane'][0]
    step = H * 0.992 / (n - 1)

    def loft(kind, items):
        sks = []
        for h, p in items:
            sk = body.newObject('Sketcher::SketchObject', 'Section')
            sk.AttachmentSupport = [(xy, '')]
            sk.MapMode = 'FlatFace'
            sk.AttachmentOffset = App.Placement(App.Vector(0, 0, h), App.Rotation())
            sk.setExpression('.AttachmentOffset.Base.z', 'Params.Height * %.6f' % (h / H))
            curve = Part.BSplineCurve()
            curve.interpolate([App.Vector(x, y, 0) for x, y in p], PeriodicFlag=True)
            sk.addGeometry(curve, False)
            sks.append(sk)
        f = body.newObject(kind, 'Loft')
        f.Profile, f.Sections, f.Ruled = sks[0], sks[1:], True
        doc.recompute()
        if f.isValid() and body.Shape.isValid():
            return
        for o in [f] + sks:  # a loft that fails: two lofts sharing the middle section
            body.removeObject(o)
            doc.removeObject(o.Name)
        if len(items) > 2:
            loft(kind, items[:len(items) // 2 + 1])
            loft(kind, items[len(items) // 2:])

    for i, ch in enumerate(chains):
        items = [(h, resample(o)) for h, o, _ in ch]
        if i and ch[0][0] > 1.5 * step:  # a chain that starts mid-part reaches into what it meets
            items.insert(0, (ch[0][0] - 1.2 * step, items[0][1]))
        if i and ch[-1][0] < H - 1.5 * step:
            items.append((ch[-1][0] + 1.2 * step, items[-1][1]))
        loft('PartDesign::AdditiveLoft', align(items))
        holes = [(h, resample(hl)) for h, _, hl in ch if hl is not None]
        if len(holes) >= 2:
            if holes[-1][0] >= ch[-1][0]:  # hole open at the end: cut through
                holes.append((holes[-1][0] + 0.02 * H, holes[-1][1]))
            if holes[0][0] <= ch[0][0]:
                holes.insert(0, (holes[0][0] - 0.02 * H, holes[0][1]))
            loft('PartDesign::SubtractiveLoft', align(holes))
    for o in doc.Objects:
        o.Visibility = o in (body, body.Tip)
    doc.recompute()
    return body

# self-test on a small box: a wrongly copied block fails here instead of later
test_doc = App.newDocument('PartFromMeshSelfTest')
try:
    shape = build(test_doc, Mesh.createBox(10, 10, 10), [0.0, 0.0, 1.0], 6).Shape
    ok = shape.isValid() and len(shape.Solids) == 1
except Exception:
    ok = False
App.closeDocument(test_doc.Name)
print('block 2 of 3 loaded' if ok else 'block 2 is wrong: run block 2 again, copied exactly')
```

## Block 3

```python
import time
import numpy as np
import FreeCAD as App, Mesh

RUN = {}

def step(doc_name, mesh_path):
    # Builds along candidate directions until one matches the mesh well (fit >= 0.93)
    # or 40 s pass. Call it again with the same arguments until it prints DONE.
    global RUN
    t0 = time.time()
    if doc_name in App.listDocuments():
        doc = App.getDocument(doc_name)
    else:
        doc = App.newDocument(doc_name)
    best = RUN.get('best')
    if RUN.get('mesh') != mesh_path or (best and doc.getObject(best[2]) is None):
        # first call (or the kept model is gone): list the slicing directions to try
        m = Mesh.Mesh(mesh_path)
        P = np.array([[p.x, p.y, p.z] for p in m.Points])
        axes = list(np.eye(3))
        for e in np.linalg.eigh(np.cov(P.T))[1].T:  # also the part's own principal axes
            if all(abs(e @ a) < 0.99 for a in axes):
                axes.append(e)
        RUN = {'mesh': mesh_path, 'm': m, 'todo': axes, 'best': None}
    while RUN['todo'] and time.time() - t0 < 40:
        if RUN['best'] and RUN['best'][0] >= 0.93:
            break
        axis = RUN['todo'].pop(0)
        before = set(o.Name for o in doc.Objects)
        try:
            body = build(doc, RUN['m'], axis)
            s = body.Shape
            ok = not s.isNull() and s.isValid() and len(s.Solids) == 1
            fit = fit_to_mesh(s, RUN['m']) if ok else -1.0
        except Exception as e:
            for name in [o.Name for o in doc.Objects if o.Name not in before]:
                if doc.getObject(name):
                    doc.removeObject(name)
            RUN = {}
            print('ERROR', type(e).__name__, e)
            print('A block was copied wrongly. Run blocks 1, 2 and 3 of the skill again,')
            print('each copied exactly, then call step again with the same arguments.')
            return
        new = [o.Name for o in doc.Objects if o.Name not in before and o.Name != 'Params']
        drop = new
        if RUN['best'] is None or fit > RUN['best'][0]:
            drop = RUN['best'][1] if RUN['best'] else []
            RUN['best'] = (fit, new, body.Name, doc.Params.Height)
        for name in drop:
            if doc.getObject(name):
                doc.removeObject(name)
        print('direction', list(np.round(axis, 2)), 'fit', round(fit, 3))
    if RUN['todo'] and RUN['best'][0] < 0.93:
        print('Not finished yet. Call step again with the same arguments.')
        return
    fit, names, body_name, height = RUN['best']
    body = doc.getObject(body_name)
    doc.Params.Height = height
    for o in doc.Objects:
        o.Visibility = o in (body, body.Tip)
    doc.recompute()
    s = body.Shape
    ok = not s.isNull() and s.isValid() and len(s.Solids) == 1
    size = s.BoundBox.DiagonalLength if ok else 0.0
    doc.Params.Height = height * 1.1  # does the named dimension drive the geometry?
    doc.recompute()
    driven = not body.Shape.isNull() and abs(body.Shape.BoundBox.DiagonalLength - size) > 1e-6
    doc.Params.Height = height
    doc.recompute()
    print('best fit', round(fit, 3), 'valid single solid', ok, 'Params.Height drives geometry', driven)
    print('DONE' if ok and driven and fit >= 0.85 else 'NOT DONE: report this')

print('block 3 of 3 loaded')
```
