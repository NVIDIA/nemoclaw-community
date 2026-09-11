# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""SRE auto-heal agent for Kubernetes and OpenShift.

Detects common production failure patterns, diagnoses them with a knowledge
base plus an optional LLM, executes only allow-listed, risk-tiered remediation
actions, verifies the outcome, learns from every incident, and notifies
operators over Slack, email, or a webhook.
"""

__version__ = "0.1.0"
