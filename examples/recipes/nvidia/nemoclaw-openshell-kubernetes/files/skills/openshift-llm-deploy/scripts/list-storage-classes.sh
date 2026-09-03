#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

storage_classes=$(oc get storageclass -o json)
printf '%s' "$storage_classes" | python3 -c '
import json
import sys

try:
    items = json.load(sys.stdin).get("items", [])
except (json.JSONDecodeError, OSError):
    raise SystemExit("STORAGE_CLASS_INVENTORY=unavailable")

entries = []
defaults = []
for item in items:
    metadata = item.get("metadata", {}) or {}
    annotations = metadata.get("annotations", {}) or {}
    name = metadata.get("name", "")
    if not name:
        continue
    is_default = any(
        annotations.get(key, "").lower() == "true"
        for key in (
            "storageclass.kubernetes.io/is-default-class",
            "storageclass.beta.kubernetes.io/is-default-class",
        )
    )
    if is_default:
        defaults.append(name)
    entries.append((
        name,
        is_default,
        item.get("provisioner", "") or "unknown",
        item.get("volumeBindingMode", "") or "Immediate",
    ))

entries.sort(key=lambda entry: entry[0])
defaults.sort()
print(f"STORAGE_CLASS_COUNT={len(entries)}")
if len(defaults) == 1:
    print(f"STORAGE_CLASS_DEFAULT={defaults[0]}")
elif not defaults:
    print("STORAGE_CLASS_DEFAULT=none")
else:
    print("STORAGE_CLASS_DEFAULT=multiple:" + ",".join(defaults))
for name, is_default, provisioner, binding_mode in entries:
    default = "true" if is_default else "false"
    print(
        "STORAGE_CLASS_OPTION="
        f"{name}\tDEFAULT={default}"
        f"\tPROVISIONER={provisioner}\tVOLUME_BINDING_MODE={binding_mode}"
    )
'
