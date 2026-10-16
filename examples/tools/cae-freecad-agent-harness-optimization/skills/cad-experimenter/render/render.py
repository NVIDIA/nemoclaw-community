# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render saved models beside their reference meshes: mesh in blue, model in orange,
one isometric panel per pair, side by side in one PNG.

    docker run --rm -v "$PWD":/w -w /w cad-render xvfb-run -a -s "-screen 0 1920x1200x24" \
      freecadcmd render.py   # with RENDER="model1.FCStd:mesh1.obj model2.FCStd:mesh2.obj" OUT=out.png
"""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Mesh

Gui.showMainWindow()
from PySide import QtGui  # noqa: E402  (needs the GUI started)

app = QtGui.QApplication.instance()
panels = []
for i, pair in enumerate(os.environ['RENDER'].split()):
    model, mesh_path = pair.split(':')
    doc = App.openDocument(os.path.abspath(model))
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)
    body = next(o for o in doc.Objects if o.TypeId == 'PartDesign::Body')
    for o in doc.Objects:
        if o.ViewObject:
            o.ViewObject.Visibility = o in (body, body.Tip)
    box = body.Shape.BoundBox
    mesh = doc.addObject('Mesh::Feature', 'Reference')
    mesh.Mesh = Mesh.Mesh(os.path.abspath(mesh_path))
    # Beside the model, offset along its shorter horizontal side.
    mesh.Placement.Base = (App.Vector(-1.3 * box.XLength, 0, 0) if box.XLength <= box.YLength
                           else App.Vector(0, 1.3 * box.YLength, 0))
    doc.recompute()
    mesh.ViewObject.ShapeColor = (0.35, 0.55, 0.85)
    for o in (body, body.Tip):
        o.ViewObject.ShapeColor, o.ViewObject.DisplayMode = (0.95, 0.55, 0.15), 'Shaded'
    view = Gui.ActiveDocument.ActiveView
    view.setAnimationEnabled(False)
    view.viewIsometric()
    for _ in range(20):
        app.processEvents()
    view.fitAll()
    for _ in range(20):
        app.processEvents()
    panels.append(f'/tmp/panel{i}.png')
    view.saveImage(panels[-1], 1400, 900, 'White')

images = [QtGui.QImage(p) for p in panels]
out = QtGui.QImage(sum(im.width() for im in images), max(im.height() for im in images),
                   QtGui.QImage.Format_RGB32)
out.fill(QtGui.QColor('white'))
painter, x = QtGui.QPainter(out), 0
for im in images:
    painter.drawImage(x, 0, im)
    x += im.width()
painter.end()
out.save(os.environ.get('OUT', 'render.png'))
os._exit(0)  # the GUI would otherwise keep running
