# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Host-side checks and the denied-action test suite for this recipe.

The modules in this package do not enforce the sandbox boundary. OpenShell
enforces it. This package checks the recipe inputs before setup and runs
allowed and denied actions against a running sandbox to record what the
boundary does.
"""
