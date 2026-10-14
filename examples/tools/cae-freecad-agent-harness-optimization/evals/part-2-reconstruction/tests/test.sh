#!/bin/bash
# One row per scored check; reward 1 only when every check passes.
mkdir -p /logs/verifier
: > /logs/verifier/results
if [ -f /app/model.FCStd ]; then
  MODEL=/app/model.FCStd MESH=/tests/reference_part_2.obj freecadcmd /tests/check_model.py \
    > /logs/verifier/check.log 2>&1
fi
for id in single-valid-solid native-feature-tree named-dimension-drives-geometry mesh-fidelity single-visible-object; do
  grep -q "^$id"$'\t' /logs/verifier/results || printf '%s\tFAIL\n' "$id" >> /logs/verifier/results
done
if grep -q $'\tFAIL$' /logs/verifier/results; then echo 0 > /logs/verifier/reward.txt; else echo 1 > /logs/verifier/reward.txt; fi
