# Generated reconstruction task

Same instruction, verifier and nine checks as the hand-made tasks in
`evals/test/part-*-reconstruction/`; only the mesh, the reference solution and `REF_FACES` in `tests/test.sh` differ.
The reference solution is the parametric FreeCAD model the mesh was exported from. The
agent's mesh (`environment/reference.obj.gz`) may be tessellated more coarsely than the
verifier's (`tests/reference.obj.gz`) and carry vertex noise.
