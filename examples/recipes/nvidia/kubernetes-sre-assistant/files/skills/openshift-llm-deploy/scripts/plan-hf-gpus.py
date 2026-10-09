#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Plan a pinned Hugging Face model's whole-GPU placement without mutating Kubernetes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_RECIPE_ARTIFACT_BYTES = 64 * 1024
MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
SHA_PATTERN = re.compile(r"[0-9a-fA-F]{40,64}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ARTIFACT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}")
GPU_PRODUCT_PATTERN = re.compile(r"NVIDIA-[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class PlannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecipeProfile:
    profile_identity: str
    gpu_product: str
    hardware_generation: str
    per_device_vram_gib: int
    required_vram_gib: int
    gpu_count: int


@dataclass(frozen=True)
class Requirements:
    required_vram_gib: int
    tensor_parallel_size: int | None
    products: tuple[str, ...]
    source: str
    recipe_sha256: str
    recipe_profiles: tuple[RecipeProfile, ...] = ()


@dataclass(frozen=True)
class NodeCapacity:
    name: str
    product: str
    memory_mib: int
    free_gpus: int


def normalize_model_id(value: str) -> str:
    value = value.removeprefix("https://huggingface.co/").strip("/")
    if not MODEL_ID_PATTERN.fullmatch(value):
        raise PlannerError("invalid-model-id")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, *_args: Any) -> None:
        raise PlannerError("metadata-redirect-disallowed")


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise PlannerError("metadata-deadline-exceeded")
    return value


def bounded_json(url: str, deadline: float, max_response_bytes: int, user_agent: str) -> tuple[Any, bytes]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    try:
        with build_opener(NoRedirect()).open(request, timeout=remaining(deadline)) as response:
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > max_response_bytes):
                raise PlannerError("metadata-response-too-large")
            reader = getattr(response, "read1", None)
            if not callable(reader):
                raise PlannerError("metadata-unavailable")
            body = bytearray()
            while True:
                read_timeout = remaining(deadline)
                try:
                    response.fp.raw._sock.settimeout(read_timeout)
                except (AttributeError, OSError):
                    pass
                chunk = reader(min(READ_CHUNK_BYTES, max_response_bytes + 1 - len(body)))
                remaining(deadline)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_response_bytes:
                    raise PlannerError("metadata-response-too-large")
    except HTTPError as exc:
        raise PlannerError(f"metadata-http-{exc.code}") from exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        if time.monotonic() >= deadline:
            raise PlannerError("metadata-deadline-exceeded") from exc
        raise PlannerError("metadata-unavailable") from exc
    try:
        return json.loads(body), bytes(body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError, ValueError) as exc:
        raise PlannerError("invalid-metadata-json") from exc


def fetch_hf_inputs(model: str, api_base: str, deadline: float, max_response_bytes: int) -> tuple[str, Any]:
    metadata, _ = bounded_json(
        f"{api_base.rstrip('/')}/api/models/{quote(model, safe='/')}", deadline, max_response_bytes,
        "hermes-hf-gpu-planner/1",
    )
    revision = metadata.get("sha") if isinstance(metadata, dict) else None
    if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
        raise PlannerError("missing-or-invalid-revision")
    try:
        config, _ = bounded_json(
            f"{api_base.rstrip('/')}/{quote(model, safe='/')}/resolve/{revision}/config.json", deadline,
            max_response_bytes, "hermes-hf-gpu-planner/1",
        )
    except PlannerError as error:
        if str(error) not in {"metadata-redirect-disallowed", "metadata-http-403"}:
            raise
        config, _ = bounded_json(
            f"{api_base.rstrip('/')}/api/resolve-cache/models/{quote(model, safe='/')}/{revision}/config.json",
            deadline, max_response_bytes, "hermes-hf-gpu-planner/1",
        )
    if not isinstance(config, dict):
        raise PlannerError("invalid-model-config")
    return revision.lower(), config


def positive_int(value: Any, reason: str) -> int:
    if isinstance(value, bool):
        raise PlannerError(reason)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError(reason) from exc
    if parsed < 1 or str(parsed) != str(value).strip():
        raise PlannerError(reason)
    return parsed


def product_requirements(value: Any, reason: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise PlannerError(reason)
    return tuple(item.strip() for item in value)


def _chart_recipe_profiles(value: Any) -> tuple[RecipeProfile, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise PlannerError("invalid-chart-recipe-artifact")
    required_fields = {
        "profileIdentity", "gpuProduct", "hardwareGeneration", "perDeviceVRAMGiB",
        "requiredModelVRAMGiB", "gpuCount", "nodeCount", "multiNode",
    }
    profiles: list[RecipeProfile] = []
    products: set[str] = set()
    identities: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != required_fields:
            raise PlannerError("invalid-chart-recipe-artifact")
        identity = raw.get("profileIdentity")
        product = raw.get("gpuProduct")
        generation = raw.get("hardwareGeneration")
        if (
            not isinstance(identity, str)
            or not ARTIFACT_TOKEN_PATTERN.fullmatch(identity)
            or identity in identities
            or not isinstance(product, str)
            or not GPU_PRODUCT_PATTERN.fullmatch(product)
            or product in products
            or not isinstance(generation, str)
            or not ARTIFACT_TOKEN_PATTERN.fullmatch(generation)
        ):
            raise PlannerError("invalid-chart-recipe-artifact")
        per_device = positive_int(
            raw.get("perDeviceVRAMGiB"), "invalid-chart-recipe-artifact"
        )
        required_vram = positive_int(
            raw.get("requiredModelVRAMGiB"), "invalid-chart-recipe-artifact"
        )
        gpu_count = positive_int(
            raw.get("gpuCount"), "invalid-chart-recipe-artifact"
        )
        if (
            per_device > 1024
            or required_vram > 65536
            or gpu_count > 8
            or per_device * gpu_count < required_vram
            or raw.get("nodeCount") != 1
            or raw.get("multiNode") is not False
        ):
            raise PlannerError("invalid-chart-recipe-artifact")
        identities.add(identity)
        products.add(product)
        profiles.append(
            RecipeProfile(
                identity, product, generation, per_device, required_vram, gpu_count
            )
        )
    return tuple(profiles)


def load_recipe_artifact(
    path: str | Path,
    *,
    expected_model: str,
    expected_source: str,
    expected_sha256: str,
) -> dict[str, Any]:
    candidate = Path(path)
    if not SHA256_PATTERN.fullmatch(expected_sha256):
        raise PlannerError("invalid-recipe-artifact-sha256")
    if not expected_source.startswith("chart-owned:") or not ARTIFACT_TOKEN_PATTERN.fullmatch(
        expected_source.removeprefix("chart-owned:")
    ):
        raise PlannerError("invalid-chart-recipe-source")
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise PlannerError("recipe-artifact-unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise PlannerError("recipe-artifact-symlink-disallowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise PlannerError("invalid-recipe-artifact")
    if metadata.st_size > MAX_RECIPE_ARTIFACT_BYTES:
        raise PlannerError("recipe-artifact-too-large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise PlannerError("invalid-recipe-artifact")
            raw = handle.read(MAX_RECIPE_ARTIFACT_BYTES + 1)
    except PlannerError:
        raise
    except OSError as exc:
        raise PlannerError("recipe-artifact-unavailable") from exc
    if len(raw) > MAX_RECIPE_ARTIFACT_BYTES:
        raise PlannerError("recipe-artifact-too-large")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise PlannerError("recipe-artifact-sha256-mismatch")
    try:
        artifact = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise PlannerError("invalid-chart-recipe-artifact") from exc
    if not isinstance(artifact, dict) or set(artifact) != {
        "schemaVersion", "model", "source", "profiles"
    }:
        raise PlannerError("invalid-chart-recipe-artifact")
    if json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode() != raw:
        raise PlannerError("recipe-artifact-not-canonical")
    if artifact.get("schemaVersion") != 1:
        raise PlannerError("invalid-chart-recipe-artifact")
    if artifact.get("model") != expected_model:
        raise PlannerError("recipe-artifact-model-mismatch")
    if artifact.get("source") != expected_source:
        raise PlannerError("recipe-artifact-source-mismatch")
    _chart_recipe_profiles(artifact.get("profiles"))
    return artifact


def make_requirements(model: str, config: dict[str, Any], recipe: Any | None, recipe_sha256: str, max_model_len: int) -> Requirements:
    if recipe is not None:
        if not isinstance(recipe, dict):
            raise PlannerError("recipe-model-mismatch")
        if recipe.get("schemaVersion") == 1:
            if recipe.get("model") != model or not str(recipe.get("source", "")).startswith("chart-owned:"):
                raise PlannerError("recipe-model-mismatch")
            profiles = _chart_recipe_profiles(recipe.get("profiles"))
            return Requirements(
                max(profile.required_vram_gib for profile in profiles),
                None,
                tuple(profile.gpu_product for profile in profiles),
                "chart-owned-vllm-recipe",
                recipe_sha256,
                profiles,
            )
        # Preserve the original normalized recipe contract while accepting the
        # current official recipes.vllm.ai model document. Task 2 performs the
        # stricter runtime/image/field validation; this planner consumes only
        # exact sizing, topology, and verified hardware evidence.
        if recipe.get("model") == model:
            required_vram = recipe.get("required_vram_gib")
            tensor_parallel = recipe.get("tensor_parallel_size")
            products = recipe.get("supported_gpu_products")
        elif recipe.get("hf_id") == model:
            variants = recipe.get("variants")
            recommended = recipe.get("recommended_command")
            meta = recipe.get("meta")
            if not isinstance(variants, dict) or not isinstance(recommended, dict) or not isinstance(meta, dict):
                raise PlannerError("invalid-official-recipe")
            default_variant = variants.get("default")
            argv = recommended.get("argv")
            hardware = meta.get("hardware")
            if not isinstance(default_variant, dict) or not isinstance(argv, list) or argv[:3] != ["vllm", "serve", model]:
                raise PlannerError("invalid-official-recipe")
            if argv.count("--tensor-parallel-size") != 1:
                raise PlannerError("invalid-recipe-tensor-parallel-size")
            tp_index = argv.index("--tensor-parallel-size") + 1
            if tp_index >= len(argv):
                raise PlannerError("invalid-recipe-tensor-parallel-size")
            if not isinstance(hardware, dict):
                raise PlannerError("invalid-recipe-hardware")
            verified = [key.upper() for key, state in hardware.items() if state == "verified" and isinstance(key, str)]
            profiles = recommended.get("by_hardware", {})
            if not isinstance(profiles, dict) or len(profiles) > 32:
                raise PlannerError("invalid-recipe-hardware")
            for product, profile_url in profiles.items():
                if (not isinstance(product, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", product)
                        or profile_url != f"/{model}/hw/{product}.json"):
                    raise PlannerError("invalid-recipe-hardware")
            required_vram = default_variant.get("vram_minimum_gb")
            tensor_parallel = argv[tp_index]
            products = default_variant.get("supported_hardware", sorted(set(verified) | {key.upper() for key in profiles}))
        else:
            raise PlannerError("recipe-model-mismatch")
        return Requirements(
            positive_int(required_vram, "invalid-recipe-required-vram"),
            positive_int(tensor_parallel, "invalid-recipe-tensor-parallel-size"),
            product_requirements(products, "invalid-recipe-hardware"),
            "official-vllm-recipe",
            recipe_sha256,
        )

    parameters = positive_int(config.get("num_parameters"), "model-sizing-evidence-unavailable")
    positive_int(config.get("num_attention_heads"), "model-sizing-evidence-unavailable")
    products = product_requirements(config.get("supported_gpu_products"), "hardware-compatibility-unproven")
    dtype = str(config.get("torch_dtype", "")).lower()
    bytes_per_parameter = {"float16": 2, "bfloat16": 2, "fp16": 2, "bf16": 2, "float8": 1, "fp8": 1}.get(dtype)
    if bytes_per_parameter is None:
        raise PlannerError("model-sizing-evidence-unavailable")
    hidden_size = positive_int(config.get("hidden_size"), "model-sizing-evidence-unavailable")
    layers = positive_int(config.get("num_hidden_layers"), "model-sizing-evidence-unavailable")
    # The 20% weight margin plus FP16 K/V cache is deliberately conservative;
    # no checkpoint file length is used as a VRAM estimate.
    weights = parameters * bytes_per_parameter * 1.20
    kv_cache = max_model_len * layers * hidden_size * 4
    return Requirements(math.ceil((weights + kv_cache) / (1024**3)), None, products, "model-config-estimate", recipe_sha256)


def gpu_request(pod: dict[str, Any]) -> int:
    spec = pod.get("spec") or {}
    def requested(containers: Any) -> int:
        total = 0
        for container in containers or []:
            value = ((container.get("resources") or {}).get("requests") or {}).get("nvidia.com/gpu", 0)
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise PlannerError("invalid-active-gpu-request") from exc
            if numeric < 0 or not numeric.is_integer():
                raise PlannerError("invalid-active-gpu-request")
            total += int(numeric)
        return total
    regular = requested(spec.get("containers"))
    restartable = 0
    init_peak = 0
    for container in spec.get("initContainers") or []:
        request = requested([container])
        if container.get("restartPolicy") == "Always":
            restartable += request
        else:
            init_peak = max(init_peak, restartable + request)
    return max(regular + restartable, init_peak)


def active_requests(pods: Any) -> dict[str, int]:
    if not isinstance(pods, dict) or not isinstance(pods.get("items"), list):
        raise PlannerError("invalid-cluster-response")
    result: dict[str, int] = {}
    for pod in pods["items"]:
        if not isinstance(pod, dict):
            raise PlannerError("invalid-cluster-response")
        phase = str((pod.get("status") or {}).get("phase", ""))
        node = str((pod.get("spec") or {}).get("nodeName", ""))
        if node and phase not in {"Succeeded", "Failed"}:
            result[node] = result.get(node, 0) + gpu_request(pod)
    return result


def tolerates_exact_ocs_storage_taint(taint: Any, allow_ocs_storage_tainted_nodes: bool) -> bool:
    return allow_ocs_storage_tainted_nodes and isinstance(taint, dict) and taint == {
        "key": "node.ocs.openshift.io/storage", "value": "true", "effect": "NoSchedule"
    }


def inspect_cluster(
    deadline: float, allow_ocs_storage_tainted_nodes: bool = False
) -> list[NodeCapacity]:
    def get_json(arguments: list[str]) -> Any:
        budget = deadline - time.monotonic()
        request_timeout_ns = int(budget * 1_000_000_000)
        if budget <= 0 or request_timeout_ns <= 0:
            raise PlannerError("cluster-inspection-deadline-exceeded")
        try:
            result = subprocess.run(
                ["oc", f"--request-timeout={request_timeout_ns}ns", *arguments],
                text=True,
                capture_output=True,
                check=False,
                timeout=budget,
            )
        except subprocess.TimeoutExpired as exc:
            raise PlannerError("cluster-inspection-deadline-exceeded") from exc
        if result.returncode != 0:
            raise PlannerError("cluster-inspection-failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PlannerError("invalid-cluster-response") from exc

    nodes = get_json(["get", "nodes", "-o", "json"])
    requests = active_requests(get_json(["get", "pods", "-A", "-o", "json"]))
    if not isinstance(nodes, dict) or not isinstance(nodes.get("items"), list):
        raise PlannerError("invalid-cluster-response")
    inventory: list[NodeCapacity] = []
    missing_memory = False
    for node in nodes["items"]:
        if not isinstance(node, dict):
            raise PlannerError("invalid-cluster-response")
        metadata, spec, status = node.get("metadata") or {}, node.get("spec") or {}, node.get("status") or {}
        allocatable = status.get("allocatable") or {}
        try:
            allocatable_gpus = int(allocatable.get("nvidia.com/gpu", 0))
        except (TypeError, ValueError) as exc:
            raise PlannerError("invalid-gpu-allocatable") from exc
        if allocatable_gpus <= 0:
            continue
        labels = metadata.get("labels") or {}
        memory_label = labels.get("nvidia.com/gpu.memory")
        try:
            memory_mib = int(memory_label)
        except (TypeError, ValueError):
            missing_memory = True
            continue
        if memory_mib <= 0:
            missing_memory = True
            continue
        ready = any(condition.get("type") == "Ready" and condition.get("status") == "True" for condition in status.get("conditions") or [])
        tainted = bool(spec.get("unschedulable")) or any(
            isinstance(taint, dict) and taint.get("effect") in {"NoSchedule", "NoExecute"}
            and not tolerates_exact_ocs_storage_taint(taint, allow_ocs_storage_tainted_nodes)
            for taint in spec.get("taints") or []
        )
        if not ready or tainted:
            continue
        name = metadata.get("name")
        product = labels.get("nvidia.com/gpu.product")
        if not isinstance(name, str) or not name or not isinstance(product, str) or not product:
            continue
        free = allocatable_gpus - requests.get(name, 0)
        if free < 0:
            raise PlannerError("active-gpu-requests-exceed-allocatable")
        inventory.append(NodeCapacity(name, product, memory_mib, free))
    if missing_memory and not inventory:
        raise PlannerError("gpu-memory-label-missing")
    if not inventory:
        raise PlannerError("no-schedulable-gpu-nodes")
    return sorted(inventory, key=lambda item: item.name)


def product_matches(product: str, requirements: tuple[str, ...]) -> bool:
    def aliases(value: str) -> set[str]:
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        classes = set(re.findall(r"(?<![a-z0-9])(a100|a10|h100|h200|l40s|l40|l4|b200|b100)(?![a-z0-9])", normalized))
        return classes or {normalized}
    product_aliases = aliases(product)
    return any(product_aliases & aliases(required) for required in requirements)


def topology_is_valid(config: dict[str, Any], gpu_count: int) -> bool:
    if config.get("num_attention_heads") is None:
        # An exact official topology is authoritative when the otherwise-valid
        # model config does not expose head counts.
        return True
    heads = positive_int(config.get("num_attention_heads"), "invalid-tensor-parallel-topology")
    kv_heads = config.get("num_key_value_heads")
    if heads % gpu_count:
        return False
    return kv_heads is None or positive_int(kv_heads, "invalid-tensor-parallel-topology") % gpu_count == 0


def choose_plan(requirements: Requirements, config: dict[str, Any], nodes: list[NodeCapacity]) -> tuple[int, list[NodeCapacity]]:
    if requirements.recipe_profiles:
        saw_compatible = False
        saw_topology = False
        for profile in sorted(
            requirements.recipe_profiles,
            key=lambda item: (item.gpu_count, item.gpu_product),
        ):
            compatible = [node for node in nodes if node.product == profile.gpu_product]
            if not compatible:
                continue
            saw_compatible = True
            if not topology_is_valid(config, profile.gpu_count):
                continue
            saw_topology = True
            viable = [
                node
                for node in compatible
                if node.free_gpus >= profile.gpu_count
                and node.memory_mib >= profile.per_device_vram_gib * 1024
                and node.memory_mib * profile.gpu_count
                >= profile.required_vram_gib * 1024
            ]
            if viable:
                return profile.gpu_count, viable
        if not saw_compatible:
            raise PlannerError("incompatible-gpu-hardware")
        if not saw_topology:
            raise PlannerError("invalid-tensor-parallel-topology")
        raise PlannerError("insufficient-whole-gpu-capacity")
    compatible = [node for node in nodes if product_matches(node.product, requirements.products)]
    if not compatible:
        raise PlannerError("incompatible-gpu-hardware")
    if requirements.tensor_parallel_size is not None:
        counts = (requirements.tensor_parallel_size,)
    else:
        counts = tuple(range(1, max(node.free_gpus for node in compatible) + 1))
    saw_topology = False
    for count in counts:
        if not topology_is_valid(config, count):
            continue
        saw_topology = True
        viable = [node for node in compatible if node.free_gpus >= count and node.memory_mib * count >= requirements.required_vram_gib * 1024]
        if viable:
            return count, viable
    if not saw_topology:
        raise PlannerError("invalid-tensor-parallel-topology")
    raise PlannerError("insufficient-whole-gpu-capacity")


def emit(**markers: str) -> None:
    for key, value in markers.items():
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--max-model-len", required=True, type=int)
    parser.add_argument("--expected-revision")
    parser.add_argument("--approved-node")
    parser.add_argument("--approved-gpu-count", type=int)
    parser.add_argument("--approved-recipe-sha256")
    parser.add_argument("--allow-ocs-storage-tainted-nodes", action="store_true")
    parser.add_argument("--api-base", default="https://huggingface.co")
    parser.add_argument("--recipe-url")
    parser.add_argument("--recipe-artifact")
    parser.add_argument("--recipe-artifact-sha256")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-response-bytes", type=int, default=MAX_RESPONSE_BYTES)
    arguments = parser.parse_args()
    try:
        if arguments.max_model_len < 1 or arguments.timeout_seconds <= 0 or arguments.max_response_bytes < 1:
            raise PlannerError("invalid-bound")
        approvals = (arguments.approved_node, arguments.approved_gpu_count, arguments.approved_recipe_sha256)
        if any(value is not None for value in approvals) and any(value is None for value in approvals):
            raise PlannerError("gpu-approval-incomplete")
        if arguments.approved_recipe_sha256 is not None and arguments.approved_recipe_sha256 != "unavailable" and not re.fullmatch(r"[0-9a-f]{64}", arguments.approved_recipe_sha256):
            raise PlannerError("invalid-approved-recipe-sha256")
        model = normalize_model_id(arguments.model)
        deadline = time.monotonic() + arguments.timeout_seconds
        revision, config = fetch_hf_inputs(model, arguments.api_base, deadline, arguments.max_response_bytes)
        if arguments.expected_revision and revision != arguments.expected_revision.lower():
            raise PlannerError("revision-changed-after-confirmation")
        recipe, recipe_sha256 = None, "unavailable"
        if arguments.recipe_url and arguments.recipe_url != "unavailable":
            if arguments.recipe_url.startswith("chart-owned:"):
                if not arguments.recipe_artifact or not arguments.recipe_artifact_sha256:
                    raise PlannerError("chart-recipe-artifact-required")
                recipe = load_recipe_artifact(
                    arguments.recipe_artifact,
                    expected_model=model,
                    expected_source=arguments.recipe_url,
                    expected_sha256=arguments.recipe_artifact_sha256,
                )
                recipe_sha256 = arguments.recipe_artifact_sha256
            else:
                if arguments.recipe_artifact or arguments.recipe_artifact_sha256:
                    raise PlannerError("unexpected-recipe-artifact")
                recipe, raw_recipe = bounded_json(arguments.recipe_url, deadline, arguments.max_response_bytes, "hermes-hf-gpu-planner/1")
                recipe_sha256 = hashlib.sha256(raw_recipe).hexdigest()
        elif arguments.recipe_artifact or arguments.recipe_artifact_sha256:
            raise PlannerError("unexpected-recipe-artifact")
        requirements = make_requirements(model, config, recipe, recipe_sha256, arguments.max_model_len)
        count, viable = choose_plan(
            requirements,
            config,
            inspect_cluster(deadline, arguments.allow_ocs_storage_tainted_nodes),
        )
        selected = viable[0]
        if arguments.approved_node is not None:
            if requirements.recipe_sha256 != arguments.approved_recipe_sha256:
                raise PlannerError("recipe-changed-after-confirmation")
            if selected.name != arguments.approved_node:
                raise PlannerError("node-changed-after-confirmation")
            if count != arguments.approved_gpu_count:
                raise PlannerError("gpu-count-changed-after-confirmation")
        emit(
            HF_GPU_PLAN_STATUS="ready", HF_GPU_PLAN_SOURCE=requirements.source,
            HF_GPU_REQUIRED_VRAM_GIB=str(requirements.required_vram_gib), HF_GPU_RECIPE_SHA256=requirements.recipe_sha256,
            HF_GPU_SELECTED_NODE=selected.name, HF_GPU_SELECTED_PRODUCT=selected.product,
            HF_GPU_PER_DEVICE_MEMORY_MIB=str(selected.memory_mib), HF_GPU_COUNT=str(count), HF_GPU_FREE_ON_NODE=str(selected.free_gpus),
        )
        for node in viable:
            print(f"HF_GPU_VIABLE_NODE={node.name}|{node.product}|{count}|{node.free_gpus}")
        return 0
    except PlannerError as exc:
        emit(
            HF_GPU_PLAN_STATUS="blocked", HF_GPU_PLAN_SOURCE="unavailable", HF_GPU_REQUIRED_VRAM_GIB="unavailable",
            HF_GPU_RECIPE_SHA256="unavailable", HF_GPU_SELECTED_NODE="unavailable", HF_GPU_SELECTED_PRODUCT="unavailable",
            HF_GPU_PER_DEVICE_MEMORY_MIB="unavailable", HF_GPU_COUNT="unavailable", HF_GPU_FREE_ON_NODE="unavailable",
            HF_GPU_PLAN_REASON=str(exc),
        )
        return 1
    except Exception:
        emit(
            HF_GPU_PLAN_STATUS="blocked", HF_GPU_PLAN_SOURCE="unavailable", HF_GPU_REQUIRED_VRAM_GIB="unavailable",
            HF_GPU_RECIPE_SHA256="unavailable", HF_GPU_SELECTED_NODE="unavailable", HF_GPU_SELECTED_PRODUCT="unavailable",
            HF_GPU_PER_DEVICE_MEMORY_MIB="unavailable", HF_GPU_COUNT="unavailable", HF_GPU_FREE_ON_NODE="unavailable",
            HF_GPU_PLAN_REASON="planner-internal-error",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
