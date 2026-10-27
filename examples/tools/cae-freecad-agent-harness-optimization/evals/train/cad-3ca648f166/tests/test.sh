#!/bin/bash
# One row per scored check; reward 1 only when every check passes.
mkdir -p /logs/verifier
: > /logs/verifier/results
if [ -f /app/model.FCStd ]; then
  # REF_FACES: faces of the reference solution, for compact-model. A model whose rebuild
  # hangs is stopped well inside Harbor's verifier timeout; checks with no row then fail.
  MODEL=/app/model.FCStd MESH=/tests/reference.obj REF_FACES=6 timeout -k 10 720 freecadcmd /tests/check_model.py \
    > /logs/verifier/check.log 2>&1
fi
for id in single-valid-solid native-feature-tree named-dimension-drives-geometry independent-dimensions mesh-fidelity no-missing-feature single-visible-object recomputes-after-reopen compact-model; do
  grep -q "^$id"$'\t' /logs/verifier/results || printf '%s\tFAIL\n' "$id" >> /logs/verifier/results
done
if grep -q $'\tFAIL$' /logs/verifier/results; then echo 0 > /logs/verifier/reward.txt; else echo 1 > /logs/verifier/reward.txt; fi
