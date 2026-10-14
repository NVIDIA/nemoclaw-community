#!/bin/bash
# Reference solution: the first-party parametric model the reference mesh was exported
# from. It is handed over exactly as the host agent would.
set -euo pipefail
mkdir -p /app
cp "$(dirname "$0")/reference-solution.FCStd" /app/model.FCStd
