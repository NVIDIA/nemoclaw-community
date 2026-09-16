# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Hermes uses this image only for the tutorial's terminal tool. Keep the image
# limited to the fixed task fixture so the agent never needs a host bind mount.
FROM nikolaik/python-nodejs:python3.11-nodejs20@sha256:8f958bdc1b4a422bfafd97cab4f69836401f616ae985d4b57a53d254f5bcb038

WORKDIR /opt/nemo-relay-hermes-tutorial
COPY sample-project/sample.py ./sample.py
