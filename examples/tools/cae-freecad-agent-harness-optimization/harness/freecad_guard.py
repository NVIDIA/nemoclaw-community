# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Platform guards installed in the FreeCAD session before each trial.

Two FreeCAD 1.1 traps that cost runs, turned into ordinary errors:

- ``Part.Shape(x)`` aborts FreeCAD outright when ``x`` is not a shape or a sequence of
  shapes (a Mesh, a number, a string): the C++ exception is never caught, and every
  open document is lost. It now raises a ``TypeError``. ``isinstance(obj, Part.Shape)``
  keeps working, and valid calls are unchanged.
- ``App.newDocument(name)`` silently creates ``name1``, ``name2``... when ``name`` is
  already open, so an agent that re-runs its setup builds in a document nobody grades.
  It now raises a ``NameError`` that says to use ``App.getDocument(name)``.
"""

GUARD = r'''
import Part
if not getattr(Part, "_shape_guard", False):
    _TopoShape = Part.Shape

    def _check(args):
        if not args:
            return
        arg = args[0]
        if isinstance(arg, _TopoShape):
            return
        if isinstance(arg, (list, tuple)) and arg and all(isinstance(x, _TopoShape) for x in arg):
            return
        raise TypeError(
            "Part.Shape() takes a shape or a list of shapes, not %s. "
            "A Mesh is measurement input: read its Points, Facets or crossSections instead."
            % type(arg).__name__)

    class _ShapeMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _TopoShape)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, _TopoShape)

    class Shape(metaclass=_ShapeMeta):
        def __new__(cls, *args, **kwargs):
            _check(args)
            return _TopoShape(*args, **kwargs)

    Shape.__doc__ = _TopoShape.__doc__
    Part.Shape = Shape
    Part._shape_guard = True

import FreeCAD
if not getattr(FreeCAD, "_document_guard", False):
    _newDocument = FreeCAD.newDocument

    def newDocument(name=None, *args, **kwargs):
        if name and name in FreeCAD.listDocuments():
            raise NameError(
                "Document %r already exists: use FreeCAD.getDocument(%r) instead of "
                "creating it again." % (name, name))
        return _newDocument(name, *args, **kwargs) if name else _newDocument(*args, **kwargs)

    newDocument.__doc__ = _newDocument.__doc__
    FreeCAD.newDocument = newDocument
    FreeCAD._document_guard = True
'''
