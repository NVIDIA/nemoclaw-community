#!/bin/sh
set -eu
mkdir -p /logs/verifier
python /tests/verify.py > /logs/verifier/results
