# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# The task image (FreeCAD 1.1.3) plus a virtual display, to render saved models headless.
#   docker build -t cad-env ../../../evals/part-1-reconstruction/environment
#   docker build -t cad-render .
FROM cad-env
RUN apt-get update -qq && apt-get install -y -qq xvfb xauth libgl1 libegl1 libxkbcommon-x11-0 \
    libxcb-cursor0 > /dev/null && rm -rf /var/lib/apt/lists/*
