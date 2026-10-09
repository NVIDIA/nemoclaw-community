#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Plan a bounded, credential-free Hugging Face model-cache PVC request."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


GIB = 1024**3
TEN_GIB = 10 * GIB
MIN_HEADROOM = 2 * GIB
MAX_RESPONSE_BYTES = 1024 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40,64}$")
APPROVED_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
QUANTITY_PATTERN = re.compile(r"^([0-9]+)(Ki|Mi|Gi|Ti|Pi|Ei)?$")
QUANTITY_FACTORS = {
    "": 1,
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": GIB,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}


class PlannerError(ValueError):
    """A fail-closed planning error safe to expose through a stable marker."""


class MetadataPlan(NamedTuple):
    revision: str
    source_bytes: int
    largest_file_bytes: int
    recommended_bytes: int


def normalize_model_id(model: str) -> str:
    normalized = model.strip()
    for prefix in ("https://huggingface.co/", "http://huggingface.co/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    normalized = normalized.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", normalized):
        raise PlannerError("invalid-model-id")
    return normalized


def sibling_size(sibling: object) -> int:
    if not isinstance(sibling, dict):
        raise PlannerError("invalid-sibling")
    size = sibling.get("size")
    if size is None and isinstance(sibling.get("lfs"), dict):
        size = sibling["lfs"].get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise PlannerError("missing-or-invalid-sibling-size")
    return size


def plan_metadata(metadata: object) -> MetadataPlan:
    if not isinstance(metadata, dict):
        raise PlannerError("invalid-metadata-json")
    gated = metadata.get("gated", False)
    if metadata.get("private") is True or gated is True or (isinstance(gated, str) and gated.casefold() not in ("", "false", "no")):
        raise PlannerError("restricted-metadata")
    revision = metadata.get("sha")
    if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
        raise PlannerError("missing-or-invalid-revision")
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list) or not siblings:
        raise PlannerError("missing-siblings")

    unique_sizes: dict[str, int] = {}
    for sibling in siblings:
        if not isinstance(sibling, dict):
            raise PlannerError("invalid-sibling")
        filename = sibling.get("rfilename")
        if not isinstance(filename, str) or not filename:
            raise PlannerError("missing-sibling-filename")
        size = sibling_size(sibling)
        previous = unique_sizes.get(filename)
        if previous is not None and previous != size:
            raise PlannerError("conflicting-duplicate-sibling")
        unique_sizes[filename] = size

    source_bytes = sum(unique_sizes.values())
    if source_bytes <= 0:
        raise PlannerError("nonpositive-source-bytes")
    largest_file_bytes = max(unique_sizes.values())
    headroom = max(MIN_HEADROOM, math.ceil(source_bytes / 10))
    required = max(TEN_GIB, 2 * source_bytes + largest_file_bytes + headroom)
    recommended = math.ceil(required / TEN_GIB) * TEN_GIB
    return MetadataPlan(revision, source_bytes, largest_file_bytes, recommended)


def gib_quantity(value: int) -> str:
    if value <= 0 or value % GIB:
        raise PlannerError("invalid-byte-quantity")
    return f"{value // GIB}Gi"


def quantity_bytes(value: object) -> int:
    if not isinstance(value, str):
        raise PlannerError("invalid-pvc-request")
    match = QUANTITY_PATTERN.fullmatch(value)
    if not match:
        raise PlannerError("invalid-pvc-request")
    result = int(match.group(1)) * QUANTITY_FACTORS[match.group(2) or ""]
    if result <= 0:
        raise PlannerError("invalid-pvc-request")
    return result


def existing_request(claim: object) -> tuple[str, int]:
    if not isinstance(claim, dict):
        raise PlannerError("invalid-existing-pvc")
    try:
        value = claim["spec"]["resources"]["requests"]["storage"]
    except (KeyError, TypeError) as exc:
        raise PlannerError("missing-existing-pvc-request") from exc
    return str(value), quantity_bytes(value)


def decide_storage(
    claim: object | None,
    storage_class: str,
    recommended_bytes: int,
    expansion_supported: bool,
    release: str,
) -> str:
    if claim is None:
        return "create"
    if not isinstance(claim, dict):
        raise PlannerError("invalid-existing-pvc")
    labels = (claim.get("metadata") or {}).get("labels") or {}
    if not isinstance(labels, dict) or labels.get("app.kubernetes.io/managed-by") != "hermes" or labels.get(
        "app.kubernetes.io/instance"
    ) != release:
        return "blocked"
    spec = claim.get("spec") or {}
    if spec.get("storageClassName") != storage_class:
        return "blocked"
    _, request_bytes = existing_request(claim)
    if request_bytes >= recommended_bytes:
        return "reuse"
    return "expand" if expansion_supported else "blocked"


def fetch_metadata(model_id: str, api_base: str, timeout_seconds: float, max_response_bytes: int) -> object:
    url = f"{api_base.rstrip('/')}/api/models/{quote(model_id, safe='/')}?blobs=true"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "hermes-hf-storage-planner/1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and (not content_length.isdecimal() or int(content_length) > max_response_bytes):
                raise PlannerError("metadata-response-too-large")
            body = response.read(max_response_bytes + 1)
    except HTTPError as exc:
        raise PlannerError(f"metadata-http-{exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PlannerError("metadata-unavailable") from exc
    if len(body) > max_response_bytes:
        raise PlannerError("metadata-response-too-large")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlannerError("invalid-metadata-json") from exc


def oc_json(arguments: list[str]) -> object | None:
    try:
        result = subprocess.run(["oc", *arguments], text=True, capture_output=True, check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise PlannerError("cluster-inspection-timeout") from exc
    except FileNotFoundError as exc:
        raise PlannerError("cluster-client-missing-from-path") from exc
    if result.returncode != 0:
        raise PlannerError("cluster-inspection-failed")
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PlannerError("invalid-cluster-response") from exc


def inspect_storage(namespace: str, release: str, storage_class: str, recommended_bytes: int) -> tuple[str, str, str]:
    claim_name = f"{release}-model-cache"
    claim = oc_json(["-n", namespace, "get", "pvc", claim_name, "-o", "json", "--ignore-not-found"])
    request = "none"
    if claim is not None:
        request, _ = existing_request(claim)
    storage = oc_json(["get", "storageclass", storage_class, "-o", "json"])
    if not isinstance(storage, dict):
        raise PlannerError("invalid-storage-class")
    expansion = (storage.get("allowVolumeExpansion") is True)
    action = decide_storage(claim, storage_class, recommended_bytes, expansion, release)
    return request, "supported" if expansion else "unsupported", action


def emit(**markers: str) -> None:
    for name, value in markers.items():
        print(f"{name}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--expected-revision")
    parser.add_argument("--approved-pvc-size")
    parser.add_argument("--approved-revision")
    parser.add_argument("--approved-metadata-reason")
    parser.add_argument("--api-base", default="https://huggingface.co")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-response-bytes", type=int, default=MAX_RESPONSE_BYTES)
    arguments = parser.parse_args()

    try:
        if arguments.timeout_seconds <= 0 or arguments.max_response_bytes <= 0:
            raise PlannerError("invalid-bound")
        model_id = normalize_model_id(arguments.model)
        if bool(arguments.approved_pvc_size) != bool(arguments.approved_revision):
            raise PlannerError("manual-approval-incomplete")
        manually_approved = bool(arguments.approved_pvc_size)
        if manually_approved:
            if arguments.approved_metadata_reason not in ("restricted-metadata", "incomplete-metadata"):
                raise PlannerError("manual-approval-reason-invalid")
            if not APPROVED_SHA_PATTERN.fullmatch(arguments.approved_revision):
                raise PlannerError("invalid-approved-revision")
            approved_bytes = quantity_bytes(arguments.approved_pvc_size)
            plan = MetadataPlan(arguments.approved_revision, 0, 0, approved_bytes)
        else:
            if arguments.approved_metadata_reason:
                raise PlannerError("manual-approval-incomplete")
            plan = plan_metadata(
                fetch_metadata(model_id, arguments.api_base, arguments.timeout_seconds, arguments.max_response_bytes)
            )
        if arguments.expected_revision and plan.revision != arguments.expected_revision:
            raise PlannerError("revision-changed-after-confirmation")
        request, expansion, action = inspect_storage(
            arguments.namespace, arguments.release, arguments.storage_class, plan.recommended_bytes
        )
        emit(
            HF_MODEL_REVISION=plan.revision,
            HF_MODEL_SOURCE_BYTES="unavailable" if manually_approved else str(plan.source_bytes),
            HF_MODEL_RECOMMENDED_PVC_SIZE=gib_quantity(plan.recommended_bytes),
            HF_MODEL_EXISTING_PVC_REQUEST=request,
            HF_MODEL_STORAGE_EXPANSION=expansion,
            HF_MODEL_STORAGE_ACTION=action,
        )
    except PlannerError as exc:
        emit(
            HF_MODEL_REVISION="unavailable",
            HF_MODEL_SOURCE_BYTES="unavailable",
            HF_MODEL_RECOMMENDED_PVC_SIZE="unavailable",
            HF_MODEL_EXISTING_PVC_REQUEST="unavailable",
            HF_MODEL_STORAGE_EXPANSION="unavailable",
            HF_MODEL_STORAGE_ACTION="blocked",
            HF_MODEL_STORAGE_REASON=str(exc),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
