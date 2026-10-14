#!/bin/bash
# Reference solution: a reconstruction that meets every requirement, produced by the
# same agent in an earlier run. It is handed over exactly as the host agent would.
set -euo pipefail
mkdir -p /app
cp "$(dirname "$0")/reference-solution.FCStd" /app/model.FCStd
