#!/bin/bash
# Reference solution: a reconstruction that meets every requirement, produced by the
# same agent in an earlier run. It is saved where the agent saves its model.
set -euo pipefail
mkdir -p /app
cp "$(dirname "$0")/reference-solution.FCStd" /app/model.FCStd
