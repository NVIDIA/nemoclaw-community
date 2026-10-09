#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Resolve an exact official vLLM recipe into immutable inert artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CATALOG_URL = "https://recipes.vllm.ai/models.json"
RECIPES_ORIGIN = "https://recipes.vllm.ai"
DOCKER_TAG_ORIGIN = "https://hub.docker.com"
MAX_CATALOG_BYTES = 512 * 1024
MAX_RECIPE_BYTES = 256 * 1024
MAX_TAG_BYTES = 64 * 1024
MAX_PLANNING_ARTIFACT_BYTES = 64 * 1024
DEADLINE_SECONDS = 15.0
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
SHA_RE = re.compile(r"[0-9a-f]{64}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SAFE_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:,+{}\"'=-]{0,1023}")
SAFE_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
IMAGE_RE = re.compile(
    r"(?:docker\.io/)?vllm/vllm-openai:([A-Za-z0-9][A-Za-z0-9._-]{0,127})(?:@(sha256:[0-9a-f]{64}))?"
)

PRODUCT_HARDWARE = {
    "NVIDIA-H100-80GB-HBM3": "h100",
    "NVIDIA-H200-141GB-HBM3E": "h200",
    "NVIDIA-B200": "b200",
    "NVIDIA-B200-SXM-180GB": "b200",
    "NVIDIA-GB200": "gb200",
}
ALLOWED_CATALOG_FIELDS = {"hf_id", "title", "provider", "url", "json", "derived_from"}
ALLOWED_MODEL_FIELDS = {
    "hf_id", "meta", "recommended_command", "model", "features", "opt_in_features",
    "variants", "hardware_overrides", "guide", "kv_offload_support",
}
ALLOWED_MODEL_RECORD_FIELDS = {
    "model_id", "min_vllm_version", "nightly_required", "docker_image", "architecture",
    "parameter_count", "active_parameters", "context_length", "base_args", "base_env", "install", "default_frontend",
}
ALLOWED_MODEL_IMAGE_FIELDS = {"nvidia", "amd"}
ALLOWED_VARIANT_FIELDS = {"precision", "vram_minimum_gb", "description"}
ALLOWED_HARDWARE_PROFILE_FIELDS = {
    "brand", "generation", "display_name", "description", "gpu_count", "vram_gb", "multi_node",
}
ALLOWED_DOCKER_TAG_FIELDS = {
    "content_type", "creator", "digest", "full_size", "id", "images", "last_updated",
    "last_updater", "last_updater_username", "media_type", "name", "repository",
    "tag_last_pulled", "tag_last_pushed", "tag_status", "v2",
}
ALLOWED_DOCKER_IMAGE_FIELDS = {
    "architecture", "digest", "features", "last_pulled", "last_pushed", "os", "os_features",
    "os_version", "size", "status", "variant",
}
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
ALLOWED_COMMAND_FIELDS = {
    "hardware", "strategy", "variant", "node_count", "deploy_type", "env", "docker_image",
    "command", "argv", "docker_command", "docker_argv", "strategy_spec", "hardware_profile",
    "alternatives", "by_hardware",
}
ALLOWED_FLAGS = {
    "--tensor-parallel-size": 1,
    "--pipeline-parallel-size": 1,
    "--no-enable-flashinfer-autotune": 0,
    "--kv-cache-dtype": 1,
    "--tool-call-parser": 1,
    "--reasoning-parser": 1,
    "--enable-auto-tool-choice": 0,
    "--enable-prefix-caching": 0,
    "--speculative-config": 1,
    "--max-model-len": 1,
    "--trust-remote-code": 0,
    "--mm-encoder-tp-mode": 1,
}
ALLOWED_ENV = {
    "VLLM_ENGINE_READY_TIMEOUT_S", "VLLM_KV_CACHE_LAYOUT", "VLLM_SSM_CONV_STATE_LAYOUT",
    "UCX_NET_DEVICES", "VLLM_USE_RUST_FRONTEND",
}
ALLOWED_METADATA_ENV = ALLOWED_ENV | {"VLLM_ROCM_USE_AITER", "VLLM_ALLOW_LONG_MAX_MODEL_LEN"}
GLM_MODEL = "zai-org/GLM-5.3-Flash"
GLM_IMAGE = "vllm/vllm-openai:glm53-flash"
GLM_PROFILE_ARGS = {
    "h100": ["--tensor-parallel-size", "8", "--no-enable-flashinfer-autotune", "--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45"],
    "h200": ["--tensor-parallel-size", "8", "--no-enable-flashinfer-autotune", "--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45"],
    "b200": ["--tensor-parallel-size", "8", "--kv-cache-dtype", "fp8", "--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45"],
    "gb200": ["--tensor-parallel-size", "4", "--kv-cache-dtype", "fp8", "--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45"],
}
GLM_HARDWARE_GENERATION = {
    "h100": "hopper", "h200": "hopper", "b200": "blackwell", "gb200": "blackwell",
}
GLM_PRODUCT_CONSTRAINTS = {
    "NVIDIA-H100-80GB-HBM3": ("h100", "hopper", 80, 8),
    "NVIDIA-H200-141GB-HBM3E": ("h200", "hopper", 141, 8),
    "NVIDIA-B200": ("b200", "blackwell", 180, 8),
    "NVIDIA-B200-SXM-180GB": ("b200", "blackwell", 180, 8),
    "NVIDIA-GB200": ("gb200", "blackwell", 192, 4),
}


class ResolutionError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fail(message: str) -> None:
    print(f"VLLM_RESOLUTION_ERROR={message}", file=sys.stderr)
    raise SystemExit(1)


def exact_https_url(path: str, *, host: str = "recipes.vllm.ai") -> str:
    if not isinstance(path, str) or len(path) > 512:
        raise ResolutionError("invalid-recipe-path")
    if not path.startswith("/") or "//" in path or not path.endswith(".json"):
        raise ResolutionError("invalid-recipe-path")
    parsed = urlsplit(RECIPES_ORIGIN + path)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.port is not None or parsed.query or parsed.fragment:
        raise ResolutionError("invalid-recipe-host")
    return parsed.geturl()


def fetch_json(url: str, output: Path, maximum: int, deadline: float) -> tuple[Any, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"recipes.vllm.ai", "hub.docker.com"} or parsed.port is not None:
        raise ResolutionError("remote-host-disallowed")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ResolutionError("remote-deadline-exceeded")
    timeout = max(1, min(15, int(remaining + 0.999)))
    curl = shutil.which("curl", path=os.environ.get("PATH"))
    if not curl:
        raise ResolutionError("curl-unavailable")
    command = [
        curl, "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2",
        "--max-redirs", "0", "--connect-timeout", "5", "--max-time", str(timeout),
        "--max-filesize", str(maximum), "--fail", "--silent", "--show-error",
        "--output", str(output), url,
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, timeout=max(1.0, remaining))
    except subprocess.TimeoutExpired as exc:
        raise ResolutionError("remote-deadline-exceeded") from exc
    if result.returncode != 0:
        reason = "remote-deadline-exceeded" if result.returncode == 28 else "remote-fetch-failed"
        raise ResolutionError(reason)
    try:
        body = output.read_bytes()
    except OSError as exc:
        raise ResolutionError("remote-fetch-failed") from exc
    if not body or len(body) > maximum:
        raise ResolutionError("remote-response-too-large")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ResolutionError("invalid-remote-json") from exc
    return value, body


def require_object(value: Any, reason: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResolutionError(reason)
    return value


def require_exact_fields(value: dict[str, Any], allowed: set[str], reason: str) -> None:
    if not set(value).issubset(allowed):
        raise ResolutionError(reason)


def safe_scalar(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not SAFE_VALUE_RE.fullmatch(value):
        raise ResolutionError(reason)
    return value


def bounded_text(value: Any, reason: str, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ResolutionError(reason)
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ResolutionError(reason)
    return value


def bounded_string_list(value: Any, reason: str, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ResolutionError(reason)
    return [bounded_text(item, reason, 1024) for item in value]


def validate_env(value: Any, allowed: set[str] = ALLOWED_ENV) -> dict[str, str]:
    env = require_object(value, "invalid-recipe-environment")
    if len(env) > 16:
        raise ResolutionError("invalid-recipe-environment")
    result: dict[str, str] = {}
    for key, raw in env.items():
        if key not in allowed:
            raise ResolutionError("recipe-environment-key-disallowed")
        result[key] = safe_scalar(raw, "recipe-environment-value-disallowed")
        if key == "VLLM_USE_RUST_FRONTEND" and result[key] not in {"0", "1"}:
            raise ResolutionError("recipe-environment-value-disallowed")
    return result


def validate_path_map(value: Any, reason: str) -> dict[str, str]:
    mapping = require_object(value, reason)
    if len(mapping) > 32:
        raise ResolutionError(reason)
    result = {}
    for key, path in mapping.items():
        if not isinstance(key, str) or not SAFE_KEY_RE.fullmatch(key):
            raise ResolutionError(reason)
        result[key] = exact_https_url(path)
    return result


def validate_hardware_profile(value: Any) -> dict[str, Any]:
    profile = require_object(value, "invalid-hardware-profile")
    require_exact_fields(profile, ALLOWED_HARDWARE_PROFILE_FIELDS | {"compute_arch"}, "unknown-hardware-profile-field")
    if "compute_arch" in profile:
        bounded_text(profile["compute_arch"], "invalid-hardware-compute-arch", 128)
    for field in ("brand", "generation", "display_name", "description"):
        bounded_text(profile.get(field), "invalid-hardware-profile-field", 2048)
    gpu_count = profile.get("gpu_count")
    vram_gb = profile.get("vram_gb")
    if type(gpu_count) is not int or not 1 <= gpu_count <= 64:
        raise ResolutionError("invalid-hardware-profile-gpu-count")
    if type(vram_gb) is not int or not 1 <= vram_gb <= 65536:
        raise ResolutionError("invalid-hardware-profile-vram")
    if type(profile.get("multi_node")) is not bool:
        raise ResolutionError("invalid-hardware-profile-topology")
    return profile


def validate_strategy_spec(value: Any) -> None:
    spec = require_object(value, "invalid-strategy-spec")
    require_exact_fields(
        spec,
        {"name", "deploy_type", "display_name", "orientation", "description", "hardware_match", "vllm_args", "parallel_flag"},
        "unknown-strategy-spec-field",
    )
    for field in ("name", "deploy_type", "display_name", "orientation", "description", "parallel_flag"):
        bounded_text(spec.get(field), "invalid-strategy-spec-field", 4096)
    match = require_object(spec.get("hardware_match"), "invalid-strategy-hardware-match")
    require_exact_fields(match, {"min_gpus", "max_gpus", "multi_node"}, "unknown-strategy-hardware-match-field")
    minimum, maximum = match.get("min_gpus"), match.get("max_gpus")
    if type(minimum) is not int or type(maximum) is not int or not 1 <= minimum <= maximum <= 64:
        raise ResolutionError("invalid-strategy-hardware-match")
    if type(match.get("multi_node")) is not bool:
        raise ResolutionError("invalid-strategy-hardware-match")
    bounded_string_list(spec.get("vllm_args"), "invalid-strategy-vllm-args")


def validate_command_record(value: Any, model: str, *, allow_by_hardware: bool) -> dict[str, Any]:
    command = require_object(value, "invalid-recommended-command")
    allowed = ALLOWED_COMMAND_FIELDS if allow_by_hardware else ALLOWED_COMMAND_FIELDS - {"by_hardware"}
    require_exact_fields(command, allowed, "unknown-runtime-recipe-field")
    for field in ("hardware", "strategy", "variant", "deploy_type", "docker_image"):
        bounded_text(command.get(field), "invalid-runtime-recipe-field", 1024)
    if type(command.get("node_count")) is not int or not 1 <= command["node_count"] <= 64:
        raise ResolutionError("invalid-runtime-recipe-node-count")
    validate_env(command.get("env"))
    bounded_text(command.get("command"), "invalid-runtime-command", 16384)
    bounded_string_list(command.get("argv"), "invalid-runtime-argv")
    bounded_text(command.get("docker_command"), "invalid-runtime-docker-command", 16384)
    bounded_string_list(command.get("docker_argv"), "invalid-runtime-docker-argv", 128)
    validate_strategy_spec(command.get("strategy_spec"))
    validate_hardware_profile(command.get("hardware_profile"))
    validate_path_map(command.get("alternatives"), "invalid-runtime-alternatives")
    if allow_by_hardware:
        validate_path_map(command.get("by_hardware"), "invalid-runtime-hardware-map")
    return command


def model_images(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"nvidia": bounded_text(value, "invalid-model-image-field", 512)}
    return require_object(value, "invalid-model-image-record")


def validate_model_record(value: Any, model: str) -> dict[str, Any]:
    record = require_object(value, "invalid-model-record")
    require_exact_fields(record, ALLOWED_MODEL_RECORD_FIELDS, "unknown-model-record-field")
    if record.get("model_id") != model:
        raise ResolutionError("recipe-model-mismatch")
    for field in ("min_vllm_version", "architecture", "parameter_count", "active_parameters"):
        bounded_text(record.get(field), "invalid-model-record-field", 1024)
    if "nightly_required" in record and type(record["nightly_required"]) is not bool:
        raise ResolutionError("invalid-model-record-field")
    if "default_frontend" in record:
        bounded_text(record["default_frontend"], "invalid-model-default-frontend", 128)
    if type(record.get("context_length")) is not int or not 1 <= record["context_length"] <= 16_777_216:
        raise ResolutionError("invalid-model-record-field")
    base_args = record.get("base_args")
    if base_args is not None:
        if not isinstance(base_args, list) or len(base_args) > 64 or not all(isinstance(item, str) for item in base_args):
            raise ResolutionError("invalid-model-record-field")
        for item in base_args:
            if len(item) > 1024:
                raise ResolutionError("invalid-model-record-field")
    images = model_images(record.get("docker_image"))
    require_exact_fields(images, ALLOWED_MODEL_IMAGE_FIELDS, "unknown-model-image-field")
    for image in images.values():
        bounded_text(image, "invalid-model-image-field", 512)
    validate_env(record.get("base_env"))
    install = require_object(record.get("install"), "invalid-model-install")
    if len(install) > 8:
        raise ResolutionError("invalid-model-install")
    for key, entry_value in install.items():
        if not isinstance(key, str) or not SAFE_KEY_RE.fullmatch(key):
            raise ResolutionError("invalid-model-install")
        entries = entry_value if key == "extras" and isinstance(entry_value, list) else [entry_value]
        if len(entries) > 8:
            raise ResolutionError("invalid-model-install-entry")
        for raw_entry in entries:
            entry = require_object(raw_entry, "invalid-model-install-entry")
            require_exact_fields(entry, {"command", "note"}, "unknown-model-install-field")
            bounded_text(entry.get("command"), "invalid-model-install-command", 16384)
            if "note" in entry:
                bounded_text(entry["note"], "invalid-model-install-note", 4096)
    return record


def validate_model_recipe(value: Any, model: str) -> dict[str, Any]:
    recipe = require_object(value, "invalid-model-recipe")
    require_exact_fields(recipe, ALLOWED_MODEL_FIELDS, "unknown-model-recipe-field")
    if "kv_offload_support" in recipe:
        offload = require_object(recipe["kv_offload_support"], "invalid-kv-offload-support")
        require_exact_fields(offload, {"offloading_cpu", "offloading_fs"}, "unknown-kv-offload-support-field")
        for value in offload.values():
            bounded_text(value, "invalid-kv-offload-support", 128)
    if recipe.get("hf_id") != model:
        raise ResolutionError("recipe-model-mismatch")
    meta = require_object(recipe.get("meta"), "invalid-model-meta")
    require_exact_fields(meta, {"title", "slug", "provider", "description", "date_updated", "date_added", "difficulty", "performance_headline", "tasks", "related_recipes", "default_hardware", "hardware", "derived_from", "variant"}, "unknown-model-meta-field")
    if "derived_from" in meta and not MODEL_RE.fullmatch(bounded_text(meta["derived_from"], "invalid-model-derived-from", 256)):
        raise ResolutionError("invalid-model-derived-from")
    if "variant" in meta and not SAFE_KEY_RE.fullmatch(bounded_text(meta["variant"], "invalid-model-meta-variant", 128)):
        raise ResolutionError("invalid-model-meta-variant")
    for field in ("title", "slug", "provider", "description", "date_updated", "difficulty", "performance_headline"):
        bounded_text(meta.get(field), "invalid-model-meta-field", 4096)
    bounded_string_list(meta.get("tasks"), "invalid-model-meta-tasks", 32)
    # Newer recipes.vllm.ai entries add these metadata fields; older ones omit
    # them. Validate them when present instead of demanding them everywhere.
    if "date_added" in meta:
        bounded_text(meta.get("date_added"), "invalid-model-meta-field", 4096)
    if "related_recipes" in meta:
        bounded_string_list(meta.get("related_recipes"), "invalid-model-meta-related-recipes", 32)
    if "default_hardware" in meta:
        bounded_text(meta.get("default_hardware"), "invalid-model-meta-field", 128)
    hardware_meta = require_object(meta.get("hardware"), "invalid-model-meta-hardware")
    if len(hardware_meta) > 32:
        raise ResolutionError("invalid-model-meta-hardware")
    for key, status in hardware_meta.items():
        if not isinstance(key, str) or not SAFE_KEY_RE.fullmatch(key):
            raise ResolutionError("invalid-model-meta-hardware")
        bounded_text(status, "invalid-model-meta-hardware", 128)
    validate_model_record(recipe.get("model"), model)
    validate_command_record(recipe.get("recommended_command"), model, allow_by_hardware=True)
    features = require_object(recipe.get("features"), "invalid-model-features")
    if len(features) > 32:
        raise ResolutionError("invalid-model-features")
    for name, raw_feature in features.items():
        if not isinstance(name, str) or not SAFE_KEY_RE.fullmatch(name):
            raise ResolutionError("invalid-model-feature")
        feature = require_object(raw_feature, "invalid-model-feature")
        require_exact_fields(feature, {"description", "args", "env", "default_mode", "modes"}, "unknown-model-feature-field")
        bounded_text(feature.get("description"), "invalid-model-feature-description", 4096)
        if "args" in feature:
            bounded_string_list(feature["args"], "invalid-model-feature-arguments")
        if "env" in feature:
            validate_env(feature["env"], ALLOWED_METADATA_ENV)
        if "modes" in feature:
            modes = require_object(feature["modes"], "invalid-model-feature-modes")
            if not modes or len(modes) > 16 or feature.get("default_mode") not in modes:
                raise ResolutionError("invalid-model-feature-modes")
            for mode_name, raw_mode in modes.items():
                if not isinstance(mode_name, str) or not SAFE_KEY_RE.fullmatch(mode_name):
                    raise ResolutionError("invalid-model-feature-mode")
                mode = require_object(raw_mode, "invalid-model-feature-mode")
                require_exact_fields(mode, {"label", "description", "variants", "args", "hardware_overrides"}, "unknown-model-feature-mode-field")
                for field in ("label", "description"):
                    bounded_text(mode.get(field), "invalid-model-feature-mode", 4096)
                if "variants" in mode:
                    bounded_string_list(mode["variants"], "invalid-model-feature-variants", 32)
                bounded_string_list(mode.get("args"), "invalid-model-feature-arguments")
                if "hardware_overrides" in mode:
                    overrides = require_object(mode["hardware_overrides"], "invalid-model-feature-overrides")
                    if len(overrides) > 32:
                        raise ResolutionError("invalid-model-feature-overrides")
                    for hardware_name, raw_override in overrides.items():
                        if not isinstance(hardware_name, str) or not SAFE_KEY_RE.fullmatch(hardware_name):
                            raise ResolutionError("invalid-model-feature-overrides")
                        override = require_object(raw_override, "invalid-model-feature-override")
                        require_exact_fields(override, {"args"}, "unknown-model-feature-override-field")
                        bounded_string_list(override.get("args"), "invalid-model-feature-arguments")
        elif "args" not in feature or "default_mode" in feature:
            raise ResolutionError("invalid-model-feature-arguments")
    opt_in = bounded_string_list(recipe.get("opt_in_features"), "invalid-opt-in-features", 32)
    if not all(item in features for item in opt_in):
        raise ResolutionError("invalid-opt-in-feature")
    variants = require_object(recipe.get("variants"), "invalid-model-variants")
    if not variants or len(variants) > 32:
        raise ResolutionError("invalid-model-variants")
    for name, raw_variant in variants.items():
        if not isinstance(name, str) or not SAFE_KEY_RE.fullmatch(name):
            raise ResolutionError("invalid-model-variant")
        variant = require_object(raw_variant, "invalid-model-variant")
        require_exact_fields(variant, ALLOWED_VARIANT_FIELDS | {
            "model_id", "json", "label", "supported_hardware", "hardware_overrides",
            "default_modes", "extra_args", "extra_env",
        }, "unknown-model-variant-field")
        if "default_modes" in variant:
            modes = require_object(variant["default_modes"], "invalid-variant-default-modes")
            if len(modes) > 32 or any(
                not isinstance(key, str) or not SAFE_KEY_RE.fullmatch(key)
                or not isinstance(value, str) or not SAFE_KEY_RE.fullmatch(value)
                for key, value in modes.items()
            ):
                raise ResolutionError("invalid-variant-default-modes")
        if "extra_args" in variant:
            bounded_string_list(variant["extra_args"], "invalid-variant-extra-arguments")
        if "extra_env" in variant:
            environment = require_object(variant["extra_env"], "invalid-variant-extra-environment")
            if len(environment) > 32:
                raise ResolutionError("invalid-variant-extra-environment")
            for key, value in environment.items():
                if not isinstance(key, str) or not SAFE_KEY_RE.fullmatch(key):
                    raise ResolutionError("invalid-variant-extra-environment")
                safe_scalar(value, "invalid-variant-extra-environment")
        if "label" in variant:
            bounded_text(variant["label"], "invalid-model-variant-label", 128)
        if "supported_hardware" in variant:
            supported = bounded_string_list(variant["supported_hardware"], "invalid-variant-hardware", 32)
            if not supported or any(not SAFE_KEY_RE.fullmatch(name) for name in supported):
                raise ResolutionError("invalid-variant-hardware")
        if "hardware_overrides" in variant:
            overrides = require_object(variant["hardware_overrides"], "invalid-variant-hardware-overrides")
            if len(overrides) > 32:
                raise ResolutionError("invalid-variant-hardware-overrides")
            for hardware_name, raw_override in overrides.items():
                if not isinstance(hardware_name, str) or not SAFE_KEY_RE.fullmatch(hardware_name):
                    raise ResolutionError("invalid-variant-hardware-overrides")
                override = require_object(raw_override, "invalid-variant-hardware-override")
                require_exact_fields(override, {"extra_args", "env", "docker_image"}, "unknown-variant-hardware-override-field")
                if "extra_args" in override:
                    bounded_string_list(override["extra_args"], "invalid-variant-hardware-arguments")
                if "env" in override:
                    validate_env(override["env"], ALLOWED_METADATA_ENV)
                if "docker_image" in override:
                    bounded_text(override["docker_image"], "invalid-variant-hardware-image", 1024)
        bounded_text(variant.get("precision"), "invalid-model-variant-field", 128)
        bounded_text(variant.get("description"), "invalid-model-variant-field", 4096)
        vram = variant.get("vram_minimum_gb")
        if type(vram) is not int or not 1 <= vram <= 65536:
            raise ResolutionError("invalid-model-variant-vram")
        if "model_id" in variant and not MODEL_RE.fullmatch(bounded_text(variant["model_id"], "invalid-model-variant-model")):
            raise ResolutionError("invalid-model-variant-model")
        if "json" in variant:
            exact_https_url(variant["json"])
    hardware_overrides = require_object(recipe.get("hardware_overrides"), "invalid-hardware-overrides")
    if len(hardware_overrides) > 32:
        raise ResolutionError("invalid-hardware-overrides")
    for name, raw_override in hardware_overrides.items():
        if not isinstance(name, str) or not SAFE_KEY_RE.fullmatch(name):
            raise ResolutionError("invalid-hardware-override")
        override = require_object(raw_override, "invalid-hardware-override")
        require_exact_fields(override, {"extra_args", "extra_env"}, "unknown-hardware-override-field")
        bounded_string_list(override.get("extra_args"), "invalid-hardware-override-arguments")
        if "extra_env" in override:
            validate_env(override["extra_env"], ALLOWED_METADATA_ENV)
    bounded_text(recipe.get("guide"), "invalid-model-guide", 65536)
    return recipe


def validate_flags(values: Any, model: str, gpus: int, *, command_prefix: bool) -> list[str]:
    if not isinstance(values, list) or len(values) > 64 or not all(isinstance(item, str) for item in values):
        raise ResolutionError("invalid-recipe-arguments")
    args = list(values)
    if command_prefix:
        if args[:3] != ["vllm", "serve", model]:
            raise ResolutionError("recipe-model-command-mismatch")
        args = args[3:]
    result: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(args):
        flag = args[index]
        arity = ALLOWED_FLAGS.get(flag)
        if arity is None or flag in seen:
            raise ResolutionError("recipe-flag-disallowed")
        seen.add(flag)
        result.append(flag)
        index += 1
        if arity:
            if index >= len(args):
                raise ResolutionError("invalid-recipe-arguments")
            result.append(safe_scalar(args[index], "recipe-argument-value-disallowed"))
            if flag == "--mm-encoder-tp-mode" and result[-1] not in {"data", "weights"}:
                raise ResolutionError("recipe-argument-value-disallowed")
            index += 1
    if "--tensor-parallel-size" not in seen:
        raise ResolutionError("recipe-tensor-parallel-size-missing")
    tp = int(result[result.index("--tensor-parallel-size") + 1]) if result[result.index("--tensor-parallel-size") + 1].isdigit() else 0
    if tp != gpus:
        raise ResolutionError("recipe-gpu-count-mismatch")
    return result


def bind_max_model_len(args: list[str], requested: int) -> list[str]:
    if "--max-model-len" not in args:
        return [*args, "--max-model-len", str(requested)]
    if args[args.index("--max-model-len") + 1] != str(requested):
        raise ResolutionError("recipe-max-model-len-mismatch")
    return args


def parse_image(value: Any, *, require_digest: bool) -> tuple[str, str, str]:
    if not isinstance(value, str):
        raise ResolutionError("invalid-vllm-image")
    match = IMAGE_RE.fullmatch(value)
    if not match:
        raise ResolutionError("vllm-image-repository-disallowed")
    tag, digest = match.groups()
    if tag == "latest" or not TAG_RE.fullmatch(tag):
        raise ResolutionError("mutable-vllm-image-disallowed")
    if require_digest and not digest:
        raise ResolutionError("mutable-vllm-image-disallowed")
    canonical = f"docker.io/vllm/vllm-openai:{tag}"
    if digest:
        canonical += f"@{digest}"
    return canonical, tag, digest or ""


def validate_catalog(value: Any, model: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise ResolutionError("invalid-recipe-catalog")
    matches = []
    for raw_entry in value:
        entry = require_object(raw_entry, "invalid-recipe-catalog-entry")
        require_exact_fields(entry, ALLOWED_CATALOG_FIELDS, "unknown-recipe-catalog-field")
        hf_id = bounded_text(entry.get("hf_id"), "invalid-recipe-catalog-entry", 256)
        if not MODEL_RE.fullmatch(hf_id):
            raise ResolutionError("invalid-recipe-catalog-entry")
        for field in ("title", "provider"):
            bounded_text(entry.get(field), "invalid-recipe-catalog-entry", 1024)
        path = bounded_text(entry.get("url"), "invalid-recipe-catalog-entry", 512)
        if not path.startswith("/") or "//" in path:
            raise ResolutionError("invalid-recipe-catalog-entry")
        exact_https_url(entry.get("json"))
        if "derived_from" in entry:
            derived = bounded_text(entry["derived_from"], "invalid-recipe-catalog-entry", 256)
            if not MODEL_RE.fullmatch(derived):
                raise ResolutionError("invalid-recipe-catalog-entry")
        if hf_id == model:
            matches.append(entry)
    return matches


def parse_overrides(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        if line.startswith("modelRuntimeOverridesJSON:"):
            raw = line.split(":", 1)[1].strip()
            try:
                decoded = json.loads(raw)
                return require_object(json.loads(decoded) if isinstance(decoded, str) else decoded, "invalid-chart-overrides")
            except (json.JSONDecodeError, ResolutionError) as exc:
                raise ResolutionError("invalid-chart-overrides") from exc
    return {}


def build_override_planning_artifact(
    override: dict[str, Any], model: str
) -> tuple[dict[str, Any], str, str]:
    allowed_model_keys = {
        "dynamoVllmRuntimeImage", "dynamoTrtllmRuntimeImage", "dynamoRuntimeVersionOverride",
        "standardVllmRecipe",
    }
    require_exact_fields(override, allowed_model_keys, "unknown-model-override-field")
    recipe = require_object(override.get("standardVllmRecipe"), "model-override-recipe-required")
    require_exact_fields(
        recipe,
        {"recipeIdentity", "recipeSHA256", "profileClass", "image", "hardwareProfiles"},
        "unknown-model-recipe-override-field",
    )
    identity = safe_scalar(recipe.get("recipeIdentity"), "invalid-model-recipe-identity")
    source = f"chart-owned:{identity}"
    profiles = require_object(
        recipe.get("hardwareProfiles"), "invalid-model-recipe-hardware-profiles"
    )
    if not profiles or len(profiles) > 16:
        raise ResolutionError("invalid-model-recipe-hardware-profiles")
    required_profile_fields = {
        "profileIdentity", "gpuProduct", "hardwareGeneration", "perDeviceVRAMGiB",
        "requiredModelVRAMGiB", "gpuCount", "nodeCount", "multiNode", "arguments", "environment",
    }
    projected_profiles: list[dict[str, Any]] = []
    for profile_product in sorted(profiles):
        if (
            not isinstance(profile_product, str)
            or not profile_product.startswith("NVIDIA-")
            or len(profile_product) > 128
        ):
            raise ResolutionError("invalid-model-recipe-hardware-product")
        candidate = require_object(
            profiles[profile_product], "invalid-model-recipe-hardware-profile"
        )
        require_exact_fields(
            candidate, required_profile_fields, "unknown-model-recipe-hardware-field"
        )
        if set(candidate) != required_profile_fields:
            raise ResolutionError("incomplete-model-recipe-hardware-field")
        profile_identity = safe_scalar(
            candidate.get("profileIdentity"), "invalid-model-profile-identity"
        )
        if candidate.get("gpuProduct") != profile_product:
            raise ResolutionError("model-recipe-gpu-product-mismatch")
        generation = safe_scalar(
            candidate.get("hardwareGeneration"), "invalid-model-hardware-generation"
        )
        per_device = candidate.get("perDeviceVRAMGiB")
        required_vram = candidate.get("requiredModelVRAMGiB")
        candidate_gpus = candidate.get("gpuCount")
        if (
            type(per_device) is not int
            or not 1 <= per_device <= 1024
            or type(required_vram) is not int
            or not 1 <= required_vram <= 65536
            or type(candidate_gpus) is not int
            or not 1 <= candidate_gpus <= 8
            or per_device * candidate_gpus < required_vram
        ):
            raise ResolutionError("invalid-model-recipe-vram-constraint")
        if candidate.get("nodeCount") != 1 or candidate.get("multiNode") is not False:
            raise ResolutionError("model-recipe-single-node-topology-required")
        if model == GLM_MODEL:
            constraint = GLM_PRODUCT_CONSTRAINTS.get(profile_product)
            if constraint is None:
                raise ResolutionError("glm53-hardware-generation-mismatch")
            _hardware, expected_generation, expected_memory, expected_gpus = constraint
            if (
                generation != expected_generation
                or per_device != expected_memory
                or required_vram != 386
                or candidate_gpus != expected_gpus
            ):
                raise ResolutionError("glm53-hardware-runtime-profile-mismatch")
        projected_profiles.append(
            {
                "profileIdentity": profile_identity,
                "gpuProduct": profile_product,
                "hardwareGeneration": generation,
                "perDeviceVRAMGiB": per_device,
                "requiredModelVRAMGiB": required_vram,
                "gpuCount": candidate_gpus,
                "nodeCount": 1,
                "multiNode": False,
            }
        )
    artifact = {
        "schemaVersion": 1,
        "model": model,
        "source": source,
        "profiles": projected_profiles,
    }
    digest = sha256_bytes(canonical_bytes(artifact))
    configured_digest = recipe.get("recipeSHA256")
    if not isinstance(configured_digest, str) or not SHA_RE.fullmatch(configured_digest):
        raise ResolutionError("invalid-model-recipe-sha256")
    if configured_digest != digest:
        raise ResolutionError("model-recipe-sha256-mismatch")
    return artifact, digest, source


def write_planning_artifact(directory: Path, artifact: dict[str, Any]) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    target = directory / "planning-recipe.json"
    target.write_bytes(canonical_bytes(artifact))
    os.chmod(target, 0o600)
    return target


def read_approved_planning_artifact(path: str) -> bytes:
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise ResolutionError("approved-planning-artifact-unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ResolutionError("approved-planning-artifact-symlink-disallowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise ResolutionError("approved-planning-artifact-invalid")
    if metadata.st_size > MAX_PLANNING_ARTIFACT_BYTES:
        raise ResolutionError("approved-planning-artifact-too-large")
    try:
        value = candidate.read_bytes()
    except OSError as exc:
        raise ResolutionError("approved-planning-artifact-unavailable") from exc
    if len(value) > MAX_PLANNING_ARTIFACT_BYTES:
        raise ResolutionError("approved-planning-artifact-too-large")
    return value


def write_artifacts(directory: Path, args: list[str], env: dict[str, str], resolution: dict[str, Any]) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    artifacts = {
        "args.json": args,
        "environment.json": env,
        "resolution.json": resolution,
    }
    for name, value in artifacts.items():
        target = directory / name
        target.write_bytes(canonical_bytes(value) + b"\n")
        os.chmod(target, 0o600)


def resolve_override(
    override: dict[str, Any], model: str, product: str, gpus: int, max_model_len: int
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    build_override_planning_artifact(override, model)
    allowed_model_keys = {
        "dynamoVllmRuntimeImage", "dynamoTrtllmRuntimeImage", "dynamoRuntimeVersionOverride",
        "standardVllmRecipe",
    }
    require_exact_fields(override, allowed_model_keys, "unknown-model-override-field")
    recipe = require_object(override.get("standardVllmRecipe"), "model-override-recipe-required")
    require_exact_fields(
        recipe,
        {"recipeIdentity", "recipeSHA256", "profileClass", "image", "hardwareProfiles"},
        "unknown-model-recipe-override-field",
    )
    identity = safe_scalar(recipe.get("recipeIdentity"), "invalid-model-recipe-identity")
    profile_class = safe_scalar(recipe.get("profileClass"), "invalid-model-profile-class")
    recipe_sha = recipe.get("recipeSHA256")
    if not isinstance(recipe_sha, str) or not SHA_RE.fullmatch(recipe_sha):
        raise ResolutionError("invalid-model-recipe-sha256")
    image, image_tag, digest = parse_image(recipe.get("image"), require_digest=True)
    profiles = require_object(recipe.get("hardwareProfiles"), "invalid-model-recipe-hardware-profiles")
    if not profiles or len(profiles) > 16:
        raise ResolutionError("invalid-model-recipe-hardware-profiles")
    validated_profiles = {}
    required_profile_fields = {
        "profileIdentity", "gpuProduct", "hardwareGeneration", "perDeviceVRAMGiB",
        "requiredModelVRAMGiB", "gpuCount", "nodeCount", "multiNode", "arguments", "environment",
    }
    for profile_product, raw_profile in profiles.items():
        if not isinstance(profile_product, str) or not profile_product.startswith("NVIDIA-") or len(profile_product) > 128:
            raise ResolutionError("invalid-model-recipe-hardware-product")
        candidate = require_object(raw_profile, "invalid-model-recipe-hardware-profile")
        require_exact_fields(candidate, required_profile_fields, "unknown-model-recipe-hardware-field")
        if set(candidate) != required_profile_fields:
            raise ResolutionError("incomplete-model-recipe-hardware-field")
        safe_scalar(candidate.get("profileIdentity"), "invalid-model-profile-identity")
        if candidate.get("gpuProduct") != profile_product:
            raise ResolutionError("model-recipe-gpu-product-mismatch")
        safe_scalar(candidate.get("hardwareGeneration"), "invalid-model-hardware-generation")
        per_device = candidate.get("perDeviceVRAMGiB")
        required_vram = candidate.get("requiredModelVRAMGiB")
        candidate_gpus = candidate.get("gpuCount")
        if (
            type(per_device) is not int or not 1 <= per_device <= 1024
            or type(required_vram) is not int or not 1 <= required_vram <= 65536
            or type(candidate_gpus) is not int or not 1 <= candidate_gpus <= 8
            or per_device * candidate_gpus < required_vram
        ):
            raise ResolutionError("invalid-model-recipe-vram-constraint")
        if candidate.get("nodeCount") != 1 or candidate.get("multiNode") is not False:
            raise ResolutionError("model-recipe-single-node-topology-required")
        candidate_args = validate_flags(candidate.get("arguments"), model, candidate_gpus, command_prefix=False)
        candidate_env = validate_env(candidate.get("environment"))
        validated_profiles[profile_product] = (candidate, candidate_args, candidate_env)
    if product not in validated_profiles:
        raise ResolutionError("model-recipe-hardware-mismatch")
    profile, args, env = validated_profiles[product]
    profile_gpu_count = profile.get("gpuCount")
    if type(profile_gpu_count) is not int or profile_gpu_count != gpus:
        raise ResolutionError("model-recipe-gpu-count-mismatch")
    if model == GLM_MODEL:
        constraint = GLM_PRODUCT_CONSTRAINTS.get(product)
        if constraint is None:
            raise ResolutionError("glm53-hardware-generation-mismatch")
        hardware, generation, per_device, expected_gpus = constraint
        if (
            profile_class != "glm53-flash-fp8"
            or image_tag != "glm53-flash"
            or profile.get("hardwareGeneration") != generation
            or profile.get("perDeviceVRAMGiB") != per_device
            or profile.get("requiredModelVRAMGiB") != 386
            or gpus != expected_gpus
            or args != GLM_PROFILE_ARGS[hardware]
            or env != {"VLLM_ENGINE_READY_TIMEOUT_S": "3600"}
        ):
            raise ResolutionError("glm53-hardware-runtime-profile-mismatch")
    args = bind_max_model_len(args, max_model_len)
    resolution = {
        "model": model, "selected_product": product, "gpu_count": gpus,
        "image": image, "source": "model-override", "reason": "exact-chart-owned-recipe",
        "recipe_url": f"chart-owned:{identity}", "recipe_sha256": recipe_sha,
        "hardware_recipe_url": f"chart-owned:{identity}:{product}",
        "hardware_recipe_sha256": sha256_bytes(canonical_bytes(profile)),
        "image_digest": digest, "hardware_profile": product,
        "profile_identity": profile["profileIdentity"],
        "arguments_sha256": sha256_bytes(canonical_bytes(args)),
        "environment_sha256": sha256_bytes(canonical_bytes(env)),
        "max_model_len": max_model_len,
    }
    return resolution, args, env


def resolve_official(
    model: str,
    product: str,
    gpus: int,
    max_model_len: int,
    approved_url: str,
    approved_sha: str,
    work: Path,
    deadline: float,
) -> tuple[dict[str, Any], list[str], dict[str, str]] | None:
    catalog_value, _ = fetch_json(CATALOG_URL, work / "catalog.json", MAX_CATALOG_BYTES, deadline)
    matches = validate_catalog(catalog_value, model)
    if not matches:
        return None
    if len(matches) != 1:
        raise ResolutionError("duplicate-exact-recipe")
    recipe_url = exact_https_url(matches[0].get("json"))
    if approved_url and recipe_url != approved_url:
        raise ResolutionError("approved-recipe-url-drift")
    recipe_value, recipe_bytes = fetch_json(recipe_url, work / "recipe.json", MAX_RECIPE_BYTES, deadline)
    recipe_sha = sha256_bytes(recipe_bytes)
    if approved_sha and recipe_sha != approved_sha:
        raise ResolutionError("approved-recipe-sha256-drift")
    recipe = validate_model_recipe(recipe_value, model)
    model_record = recipe["model"]
    command = recipe["recommended_command"]
    hardware = PRODUCT_HARDWARE.get(product)
    if hardware is None:
        raise ResolutionError("selected-gpu-product-unmapped")
    hardware_paths = command["by_hardware"]
    hardware_url = exact_https_url(hardware_paths.get(hardware))
    profile_value, profile_bytes = fetch_json(hardware_url, work / "hardware.json", MAX_RECIPE_BYTES, deadline)
    profile = validate_command_record(profile_value, model, allow_by_hardware=False)
    node_count = profile.get("node_count")
    if profile.get("hardware") != hardware or profile.get("deploy_type") != "single_node" or type(node_count) is not int or node_count != 1:
        raise ResolutionError("recipe-hardware-profile-mismatch")
    hardware_profile = profile["hardware_profile"]
    profile_gpu_count = hardware_profile.get("gpu_count")
    if type(profile_gpu_count) is not int or not 1 <= gpus <= profile_gpu_count or hardware_profile.get("multi_node") is not False:
        raise ResolutionError("recipe-gpu-count-mismatch")
    root_image_record = model_images(model_record.get("docker_image"))
    require_exact_fields(root_image_record, ALLOWED_MODEL_IMAGE_FIELDS, "unknown-model-image-field")
    root_nvidia_image = root_image_record.get("nvidia")
    if root_nvidia_image != profile.get("docker_image"):
        raise ResolutionError("recipe-image-mismatch")
    _, tag, _ = parse_image(profile.get("docker_image"), require_digest=False)
    if model == GLM_MODEL:
        if profile.get("docker_image") != GLM_IMAGE or hardware not in {"h100", "h200", "b200", "gb200"}:
            raise ResolutionError("glm53-dedicated-recipe-required")
        variants = require_object(recipe.get("variants"), "glm53-variants-missing")
        default_variant = require_object(variants.get("default"), "glm53-default-variant-missing")
        require_exact_fields(default_variant, ALLOWED_VARIANT_FIELDS, "unknown-glm53-variant-field")
        if default_variant.get("precision") != "fp8" or default_variant.get("vram_minimum_gb") != 386:
            raise ResolutionError("glm53-fp8-constraint-mismatch")
        profile_vram = hardware_profile.get("vram_gb")
        if (
            hardware_profile.get("brand") != "NVIDIA"
            or hardware_profile.get("generation") != GLM_HARDWARE_GENERATION[hardware]
            or not isinstance(profile_vram, int)
            or isinstance(profile_vram, bool)
            or profile_vram < 386
        ):
            raise ResolutionError("glm53-hardware-generation-mismatch")
    args = validate_flags(profile.get("argv"), model, gpus, command_prefix=True)
    env = validate_env(profile.get("env"))
    if model == GLM_MODEL:
        if args != GLM_PROFILE_ARGS[hardware] or env != {"VLLM_ENGINE_READY_TIMEOUT_S": "3600"}:
            raise ResolutionError("glm53-hardware-runtime-profile-mismatch")
    args = bind_max_model_len(args, max_model_len)
    tag_url = f"{DOCKER_TAG_ORIGIN}/v2/repositories/vllm/vllm-openai/tags/{tag}"
    tag_value, _ = fetch_json(tag_url, work / "tag.json", MAX_TAG_BYTES, deadline)
    tag_record = require_object(tag_value, "invalid-docker-tag-record")
    require_exact_fields(tag_record, ALLOWED_DOCKER_TAG_FIELDS, "unknown-docker-tag-field")
    digest = tag_record.get("digest")
    images = tag_record.get("images")
    if not isinstance(images, list) or len(images) > 32:
        raise ResolutionError("docker-tag-linux-amd64-index-unverified")
    has_amd64 = False
    for raw_image in images:
        image_record = require_object(raw_image, "invalid-docker-image-record")
        require_exact_fields(image_record, ALLOWED_DOCKER_IMAGE_FIELDS, "unknown-docker-image-field")
        child_digest = image_record.get("digest")
        if (
            image_record.get("os") == "linux"
            and image_record.get("architecture") == "amd64"
            and image_record.get("status") == "active"
            and isinstance(child_digest, str)
            and DIGEST_RE.fullmatch(child_digest)
        ):
            has_amd64 = True
    if tag_record.get("name") != tag or tag_record.get("tag_status") != "active" or tag_record.get("media_type") not in INDEX_MEDIA_TYPES or not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest) or not has_amd64:
        raise ResolutionError("docker-tag-linux-amd64-index-unverified")
    image = f"docker.io/vllm/vllm-openai:{tag}@{digest}"
    resolution = {
        "model": model, "selected_product": product, "gpu_count": gpus,
        "image": image, "source": "official-vllm-recipe",
        "reason": "exact-catalog-model-hardware-and-linux-amd64-index-verified",
        "recipe_url": recipe_url, "recipe_sha256": recipe_sha,
        "hardware_recipe_url": hardware_url,
        "hardware_recipe_sha256": sha256_bytes(profile_bytes),
        "image_digest": digest, "hardware_profile": hardware,
        "profile_identity": hardware_url,
        "arguments_sha256": sha256_bytes(canonical_bytes(args)),
        "environment_sha256": sha256_bytes(canonical_bytes(env)),
        "max_model_len": max_model_len,
    }
    return resolution, args, env


def resolve_catalog_identity(
    model: str, overrides: dict[str, Any], work: Path, deadline: float
) -> tuple[str, str, str, dict[str, Any] | None]:
    exact_override = overrides.get(model)
    if exact_override is not None:
        override = require_object(exact_override, "invalid-model-override")
        artifact, recipe_sha, source = build_override_planning_artifact(override, model)
        return source, recipe_sha, "model-override", artifact
    catalog_value, _ = fetch_json(CATALOG_URL, work / "catalog.json", MAX_CATALOG_BYTES, deadline)
    matches = validate_catalog(catalog_value, model)
    if not matches:
        return "unavailable", "unavailable", "generic", None
    if len(matches) != 1:
        raise ResolutionError("duplicate-exact-recipe")
    recipe_url = exact_https_url(matches[0].get("json"))
    recipe_value, recipe_bytes = fetch_json(recipe_url, work / "recipe.json", MAX_RECIPE_BYTES, deadline)
    validate_model_recipe(recipe_value, model)
    return recipe_url, sha256_bytes(recipe_bytes), "official-vllm-recipe", None


def emit(resolution: dict[str, Any], directory: Path) -> None:
    mapping = {
        "VLLM_IMAGE": resolution["image"],
        "VLLM_IMAGE_SOURCE": resolution["source"],
        "VLLM_IMAGE_REASON": resolution["reason"],
        "VLLM_RECIPE_URL": resolution["recipe_url"],
        "VLLM_RECIPE_SHA256": resolution["recipe_sha256"],
        "VLLM_HARDWARE_RECIPE_URL": resolution["hardware_recipe_url"],
        "VLLM_HARDWARE_RECIPE_SHA256": resolution["hardware_recipe_sha256"],
        "VLLM_IMAGE_DIGEST": resolution["image_digest"],
        "VLLM_HARDWARE_PROFILE": resolution["hardware_profile"],
        "VLLM_PROFILE_IDENTITY": resolution["profile_identity"],
        "VLLM_ARGS_SHA256": resolution["arguments_sha256"],
        "VLLM_ENV_SHA256": resolution["environment_sha256"],
        "VLLM_ARGS_ARTIFACT": directory / "args.json",
        "VLLM_ENV_ARTIFACT": directory / "environment.json",
        "VLLM_RESOLUTION_ARTIFACT": directory / "resolution.json",
    }
    for key, value in mapping.items():
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--default-image", default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--selected-product", default="")
    parser.add_argument("--gpu-count", default=0, type=int)
    parser.add_argument("--max-model-len", default=0, type=int)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--overrides-file", default="")
    parser.add_argument("--approved-recipe-url", default="")
    parser.add_argument("--approved-recipe-sha256", default="")
    parser.add_argument("--approved-planning-artifact", default="")
    parser.add_argument("--expected-resolution", default="")
    parser.add_argument("--catalog-only", action="store_true")
    args = parser.parse_args()
    if not MODEL_RE.fullmatch(args.model):
        raise ResolutionError("invalid-resolution-input")
    os.umask(0o077)
    overrides = parse_overrides(args.overrides_file)
    if args.catalog_only:
        with tempfile.TemporaryDirectory(prefix="hermes-vllm-catalog.") as temporary:
            recipe_url, recipe_sha, source, planning_artifact = resolve_catalog_identity(
                args.model, overrides, Path(temporary), time.monotonic() + DEADLINE_SECONDS
            )
        planning_artifact_path = "unavailable"
        if planning_artifact is not None:
            if not args.artifact_dir:
                raise ResolutionError("chart-owned-planning-artifact-dir-required")
            planning_artifact_path = str(
                write_planning_artifact(Path(args.artifact_dir), planning_artifact)
            )
        print(f"VLLM_RECIPE_URL={recipe_url}")
        print(f"VLLM_RECIPE_SHA256={recipe_sha}")
        print(f"VLLM_RECIPE_SOURCE={source}")
        print(f"VLLM_RECIPE_ARTIFACT={planning_artifact_path}")
        return 0
    if args.gpu_count < 1 or args.gpu_count > 8 or args.max_model_len < 1 or not args.artifact_dir:
        raise ResolutionError("invalid-resolution-input")
    parse_image(args.default_image, require_digest=True)
    if args.approved_recipe_sha256 and not SHA_RE.fullmatch(args.approved_recipe_sha256):
        raise ResolutionError("invalid-approved-recipe-sha256")
    artifact_dir = Path(args.artifact_dir)
    exact_override = overrides.get(args.model)
    if exact_override is not None:
        resolution, profile_args, env = resolve_override(
            require_object(exact_override, "invalid-model-override"),
            args.model, args.selected_product, args.gpu_count, args.max_model_len,
        )
        planning_artifact, planning_sha, planning_source = build_override_planning_artifact(
            require_object(exact_override, "invalid-model-override"), args.model
        )
        if args.approved_recipe_url and args.approved_recipe_url != planning_source:
            raise ResolutionError("approved-recipe-url-drift")
        if args.approved_recipe_sha256 and args.approved_recipe_sha256 != planning_sha:
            raise ResolutionError("approved-recipe-sha256-drift")
        if args.approved_recipe_url or args.approved_recipe_sha256:
            if not args.approved_planning_artifact:
                raise ResolutionError("approved-planning-artifact-required")
            approved_artifact = read_approved_planning_artifact(
                args.approved_planning_artifact
            )
            if approved_artifact != canonical_bytes(planning_artifact):
                raise ResolutionError("approved-planning-artifact-content-drift")
    else:
        with tempfile.TemporaryDirectory(prefix="hermes-vllm-recipe.") as temporary:
            resolved = resolve_official(
                args.model, args.selected_product, args.gpu_count, args.max_model_len,
                args.approved_recipe_url, args.approved_recipe_sha256,
                Path(temporary), time.monotonic() + DEADLINE_SECONDS,
            )
        if resolved is None:
            image, _, digest = parse_image(args.default_image, require_digest=True)
            profile_args = [
                "--tensor-parallel-size", str(args.gpu_count), "--trust-remote-code",
                "--max-model-len", str(args.max_model_len),
            ]
            env = {}
            resolution = {
                "model": args.model, "selected_product": args.selected_product,
                "gpu_count": args.gpu_count, "image": image, "source": "chart-default",
                "reason": "no-exact-official-or-chart-owned-recipe",
                "recipe_url": "unavailable", "recipe_sha256": "unavailable",
                "hardware_recipe_url": "unavailable", "hardware_recipe_sha256": "unavailable",
                "image_digest": digest, "hardware_profile": "generic",
                "profile_identity": "generic",
                "arguments_sha256": sha256_bytes(canonical_bytes(profile_args)),
                "environment_sha256": sha256_bytes(canonical_bytes(env)),
                "max_model_len": args.max_model_len,
            }
        else:
            resolution, profile_args, env = resolved
    if args.expected_resolution:
        try:
            expected = json.loads(Path(args.expected_resolution).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResolutionError("invalid-expected-resolution") from exc
        if expected != resolution:
            raise ResolutionError("immutable-vllm-resolution-drift")
    write_artifacts(artifact_dir, profile_args, env, resolution)
    emit(resolution, artifact_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ResolutionError as error:
        fail(str(error))
