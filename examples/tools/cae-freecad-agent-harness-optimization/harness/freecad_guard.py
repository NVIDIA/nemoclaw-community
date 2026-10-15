# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Platform guard installed in the FreeCAD session before each trial.

FreeCAD 1.1 aborts outright when ``Part.Shape(x)`` is given anything that is not a
shape or a sequence of shapes (a Mesh, a number, a string): the C++ exception is never
caught, and every open document is lost. The guard makes that call raise a Python
``TypeError`` instead, so a mistake costs the agent one failed call, not the run.
``isinstance(obj, Part.Shape)`` keeps working, and valid calls are unchanged.
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
'''
