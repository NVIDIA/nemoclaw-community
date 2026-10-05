Turn the mesh at
`@MESH_PATH@`
into a fully parametric FreeCAD model that a CAD designer can open and edit.

Build it in a new FreeCAD document named `EvalMug`, constructed
from scratch. Other documents may be open from earlier work: do not open,
copy, merge or `saveCopy` any of them. Confirm the document does not
already exist before you create it.

Requirements:
- The result must be a single valid solid.
- It must be a native sketch-based PartDesign feature tree, with sketches
  driving features, not a stack of fused boolean primitives.
- A designer must be able to change a named dimension and have the model rebuild.
- It must match the original mesh closely.

Leave the document open when you finish, with exactly one object visible:
the finished model. The result is scored from the open document.

Do not take screenshots; verify numerically.
