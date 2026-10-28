# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# The verifier image every task's tests/Dockerfile starts from: FreeCAD 1.1.3 (the same
# version as the agent's image) to open the saved document, re-run the dimension checks and
# recompute IoU offline, and the grader in /grader. Build it before a run:
#   docker build -t cad-verifier evals/verifier
FROM condaforge/miniforge3:24.11.3-2
RUN mamba install -y -q python=3.12 freecad=1.1.3 numpy && mamba clean -a -y
COPY check_model.py iou_core.py iou_math.py grade.sh /grader/
