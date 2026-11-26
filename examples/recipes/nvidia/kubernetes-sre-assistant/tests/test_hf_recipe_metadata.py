# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path
import runpy
import unittest

MODEL = "zai-org/GLM-5.3-Flash"
RESOLVER = Path(__file__).resolve().parents[1] / "files/skills/openshift-llm-deploy/scripts/resolve-vllm-recipe.py"

def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))

def model_recipe() -> dict[str, object]:
    return {
        "hf_id": MODEL,
        "meta": {
            "title": "GLM-5.3-Flash",
            "slug": "glm-5.3-flash",
            "provider": "GLM (Z-AI)",
            "description": "fixture",
            "date_updated": "2026-08-26",
            "difficulty": "advanced",
            "tasks": ["text"],
            "performance_headline": "fixture",
            "hardware": {"h100": "verified", "b200": "verified"},
        },
        "recommended_command": {
            "hardware": "h100",
            "strategy": "single_node_tp",
            "variant": "default",
            "node_count": 1,
            "deploy_type": "single_node",
            "env": {"VLLM_ENGINE_READY_TIMEOUT_S": "3600"},
            "docker_image": "vllm/vllm-openai:glm53-flash",
            "command": "ignored inert prose",
            "argv": ["vllm", "serve", MODEL, "--tensor-parallel-size", "8"],
            "docker_command": "ignored inert prose",
            "docker_argv": ["docker", "run"],
            "strategy_spec": {
                "name": "single_node_tp",
                "deploy_type": "single_node",
                "display_name": "Tensor Parallel",
                "orientation": "latency",
                "description": "fixture",
                "hardware_match": {"min_gpus": 1, "max_gpus": 8, "multi_node": False},
                "vllm_args": [],
                "parallel_flag": "--tensor-parallel-size",
            },
            "hardware_profile": {
                "brand": "NVIDIA",
                "generation": "hopper",
                "display_name": "H100",
                "description": "fixture",
                "gpu_count": 8,
                "vram_gb": 640,
                "multi_node": False,
            },
            "alternatives": {},
            "by_hardware": {
                "h100": "/zai-org/GLM-5.3-Flash/hw/h100.json",
                "b200": "/zai-org/GLM-5.3-Flash/hw/b200.json",
            },
        },
        "model": {
            "model_id": MODEL,
            "min_vllm_version": "0.27.0",
            "nightly_required": True,
            "docker_image": {
                "nvidia": "vllm/vllm-openai:glm53-flash",
                "amd": "vllm/vllm-openai-rocm:glm53-flash",
            },
            "architecture": "moe",
            "parameter_count": "321B",
            "active_parameters": "18B",
            "context_length": 1048576,
            "base_env": {"VLLM_ENGINE_READY_TIMEOUT_S": "3600"},
            "install": {},
        },
        "features": {},
        "opt_in_features": [],
        "variants": {
            "default": {
                "precision": "fp8",
                "vram_minimum_gb": 386,
                "description": "fixture",
            }
        },
        "hardware_overrides": {
            "hopper": {"extra_args": ["--no-enable-flashinfer-autotune"]},
            "blackwell": {"extra_args": ["--kv-cache-dtype", "fp8"]},
        },
        "guide": "ignored inert prose",
    }

class RecipeMetadataTests(unittest.TestCase):
    def test_variant_metadata_rejects_unknown_nested_commands(self):
        resolver = runpy.run_path(str(RESOLVER.with_name("resolve-vllm-recipe.py")))
        recipe = model_recipe()
        recipe["variants"]["default"]["hardware_overrides"] = {"b200": {"command": "execute something"}}
        with self.assertRaisesRegex(resolver["ResolutionError"], "unknown-variant-hardware-override-field"):
            resolver["validate_model_recipe"](recipe, MODEL)

    def test_optional_variant_modes_and_install_metadata_remain_inert(self):
        resolver = runpy.run_path(str(RESOLVER.with_name("resolve-vllm-recipe.py")))
        recipe = model_recipe()
        original = compact(recipe["recommended_command"])
        recipe["variants"]["default"].update(
            default_modes={"spec_decoding": "qwen3_5_mtp"},
            extra_args=["--quantization", "ascend"],
            extra_env={"HCCL_BUFFSIZE": "512", "OMP_NUM_THREADS": "1"},
        )
        validated = resolver["validate_model_recipe"](recipe, MODEL)
        self.assertEqual(compact(validated["recommended_command"]), original)

    def test_variant_extra_metadata_rejects_commands_and_invalid_modes(self):
        resolver = runpy.run_path(str(RESOLVER.with_name("resolve-vllm-recipe.py")))
        for field, value in [("extra_env", {"X": "bad\nvalue"}), ("default_modes", {"bad/key": "mode"})]:
            with self.subTest(field=field):
                recipe = model_recipe()
                recipe["variants"]["default"][field] = value
                with self.assertRaises(resolver["ResolutionError"]):
                    resolver["validate_model_recipe"](recipe, MODEL)
