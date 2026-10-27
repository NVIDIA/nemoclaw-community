# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render saved models beside their reference meshes (mesh blue, model orange), from
several directions: one row per model, one column per view, in one PNG.

    docker run --rm -v "$PWD":/w -w /w cad-env xvfb-run -a -s "-screen 0 1920x1200x24" \
      freecadcmd render.py   # with RENDER="model1.FCStd:mesh1.obj[.gz] ..." OUT=out.png
                             # VIEWS=iso,front,right,top (default; also rear, left, bottom)
                             # INPLACE=1: the mesh translucent over the model, in place
"""
import gzip
import os
import shutil

import FreeCAD as App
import FreeCADGui as Gui
import Mesh

Gui.showMainWindow()
from PySide import QtGui  # noqa: E402  (needs the GUI started)

app = QtGui.QApplication.instance()
VIEWS = os.environ.get('VIEWS', 'iso,front,right,top').split(',')
INPLACE = os.environ.get('INPLACE') == '1'  # shows misplacement; beside shows shape better
METHODS = {'iso': 'viewIsometric', 'front': 'viewFront', 'rear': 'viewRear', 'right': 'viewRight',
           'left': 'viewLeft', 'top': 'viewTop', 'bottom': 'viewBottom'}
W, H = 1000, 700


def settle():
    for _ in range(20):
        app.processEvents()


rows = []
for pair in os.environ['RENDER'].split():
    model, mesh_path = pair.split(':')
    doc = App.openDocument(os.path.abspath(model))
    for o in doc.Objects:  # rebuild as the verifier does, so the render shows what is graded
        o.touch()
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)
    body = next(o for o in doc.Objects if o.TypeId == 'PartDesign::Body')
    for o in doc.Objects:
        if o.ViewObject:
            o.ViewObject.Visibility = o in (body, body.Tip)
    box = body.Shape.BoundBox
    mesh = doc.addObject('Mesh::Feature', 'Reference')
    if mesh_path.endswith('.gz'):  # the tasks' meshes are stored gzipped
        with gzip.open(mesh_path) as src, open('/tmp/mesh.obj', 'wb') as dst:
            shutil.copyfileobj(src, dst)
        mesh_path = '/tmp/mesh.obj'
    mesh.Mesh = Mesh.Mesh(os.path.abspath(mesh_path))
    if not INPLACE:  # beside the model, offset along its shorter horizontal side
        mesh.Placement.Base = (App.Vector(-1.3 * box.XLength, 0, 0) if box.XLength <= box.YLength
                               else App.Vector(0, 1.3 * box.YLength, 0))
    doc.recompute()
    mesh.ViewObject.ShapeColor = (0.35, 0.55, 0.85)
    mesh.ViewObject.Transparency = 60 if INPLACE else 0
    for o in (body, body.Tip):
        o.ViewObject.ShapeColor, o.ViewObject.DisplayMode = (0.95, 0.55, 0.15), 'Shaded'
    view = Gui.ActiveDocument.ActiveView
    view.setAnimationEnabled(False)
    row = []
    for name in VIEWS:
        getattr(view, METHODS[name])()
        settle()
        view.fitAll()
        settle()
        path = f'/tmp/panel{len(rows)}_{name}.png'
        view.saveImage(path, W, H, 'White')
        row.append((name, path))
    rows.append(row)
    App.closeDocument(doc.Name)

out = QtGui.QImage(W * len(VIEWS), H * len(rows), QtGui.QImage.Format_RGB32)
out.fill(QtGui.QColor('white'))
painter = QtGui.QPainter(out)
painter.setFont(QtGui.QFont('Sans', 20))
for r, row in enumerate(rows):
    for c, (name, path) in enumerate(row):
        painter.drawImage(c * W, r * H, QtGui.QImage(path))
        painter.drawText(c * W + 16, r * H + 36, name)
painter.end()
out.save(os.environ.get('OUT', 'render.png'))
os._exit(0)  # the GUI would otherwise keep running
