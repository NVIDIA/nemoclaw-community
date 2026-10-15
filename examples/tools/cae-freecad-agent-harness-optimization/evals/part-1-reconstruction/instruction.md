Turn the mesh at
`/app/reference.obj`
into a fully parametric FreeCAD model that a CAD designer can open and edit.

Build it from scratch in a new FreeCAD document.

Requirements:
- The result must be a single valid solid.
- It must be a native sketch-based PartDesign feature tree, with sketches
  driving features, not a stack of fused boolean primitives or a scripted
  base shape.
- A designer must be able to change a named dimension and have the model rebuild.
- It must reopen from the saved file and recompute without errors.
- It must match the original mesh closely.

Save the finished model to `/app/model.FCStd`, with exactly one object
visible when the file is opened: the finished model. The result is scored
from that file.

Verify numerically.
