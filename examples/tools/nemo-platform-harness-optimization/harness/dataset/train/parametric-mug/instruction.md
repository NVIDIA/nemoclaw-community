Turn the mesh at
`@MESH_PATH@`
into a fully parametric FreeCAD model that a CAD designer can open and edit.

Build it in a new FreeCAD document named `EvalMug`.

Requirements:
- The result must be a single valid solid.
- It must be a native sketch-based PartDesign feature tree — sketches driving
  features — not a stack of fused boolean primitives.
- A designer must be able to change a named dimension and have the model rebuild.
- It must match the original mesh closely.

Leave the document open when you finish, with exactly one object visible:
the finished model. The result is scored from the open document.

Do not take screenshots; verify numerically.
