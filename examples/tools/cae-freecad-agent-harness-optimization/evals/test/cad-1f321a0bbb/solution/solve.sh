#!/bin/bash
# Reference solution: the first-party parametric model the reference mesh was exported
# from. It is saved where the agent saves its model.
set -euo pipefail
mkdir -p /app
cp "$(dirname "$0")/reference-solution.FCStd" /app/model.FCStd
