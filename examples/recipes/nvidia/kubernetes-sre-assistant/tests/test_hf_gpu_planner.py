# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock


CHART_DIR = Path(__file__).resolve().parents[1]
PLANNER = CHART_DIR / "files" / "skills" / "openshift-llm-deploy" / "scripts" / "plan-hf-gpus.py"


def load_planner():
    module_name = "chart_hf_gpu_planner_deadline"
    spec = importlib.util.spec_from_file_location(module_name, PLANNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load GPU planner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def chart_recipe_artifact() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "model": "example/model",
        "source": "chart-owned:example-model-v1",
        "profiles": [
            {
                "profileIdentity": "example-h100-tp2-v1",
                "gpuProduct": "NVIDIA-H100-80GB-HBM3",
                "hardwareGeneration": "hopper",
                "perDeviceVRAMGiB": 80,
                "requiredModelVRAMGiB": 120,
                "gpuCount": 2,
                "nodeCount": 1,
                "multiNode": False,
            }
        ],
    }


class PlannerServer:
    def __init__(
        self,
        metadata: object,
        config: object,
        recipe: object,
        delay: float = 0,
        raw_payloads: dict[str, bytes] | None = None,
        omit_content_length: bool = False,
        dribble_interval: float = 0,
    ) -> None:
        self.payloads = {
            "/api/models/example/model": metadata,
            "/example/model/resolve/" + str(metadata["sha"]) + "/config.json": config,
            "/recipe.json": recipe,
        }
        owner = self
        self.raw_payloads = raw_payloads or {}
        self.omit_content_length = omit_content_length
        self.dribble_interval = dribble_interval

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if delay:
                    time.sleep(delay)
                if self.path in owner.raw_payloads:
                    body = owner.raw_payloads[self.path]
                else:
                    payload = owner.payloads.get(self.path)
                    if payload is None:
                        self.send_error(404)
                        return
                    body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if not owner.omit_content_length:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    if owner.dribble_interval:
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(owner.dribble_interval)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "PlannerServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


def nodes(memory: str = "81920", ready: bool = True, taints: list[dict] | None = None, product: str = "NVIDIA-H100-80GB-HBM3", second: bool = True, gpu_count: int = 4) -> dict:
    items = [
            {
                "metadata": {"name": "gpu-a", "labels": {"nvidia.com/gpu.product": product, "nvidia.com/gpu.memory": memory}},
                "spec": {"taints": taints or []},
                "status": {"allocatable": {"nvidia.com/gpu": str(gpu_count)}, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
            },
            {
                "metadata": {"name": "gpu-b", "labels": {"nvidia.com/gpu.product": product, "nvidia.com/gpu.memory": memory}},
                "spec": {},
                "status": {"allocatable": {"nvidia.com/gpu": "2"}, "conditions": [{"type": "Ready", "status": "True"}]},
            },
        ]
    return {"items": items if second else items[:1]}


class HuggingFaceGpuPlannerTests(unittest.TestCase):
    def test_explicit_same_model_hardware_profiles_support_planning(self):
        planner = load_planner()
        recipe = {
            "hf_id": "example/model",
            "variants": {"default": {"vram_minimum_gb": 67}},
            "recommended_command": {
                "argv": ["vllm", "serve", "example/model", "--tensor-parallel-size", "1"],
                "by_hardware": {"b200": "/example/model/hw/b200.json"},
            },
            "meta": {"hardware": {"gb300": "verified"}},
        }
        requirements = planner.make_requirements("example/model", {}, recipe, "a" * 64, 32768)
        count, viable = planner.choose_plan(requirements, {}, [
            planner.NodeCapacity("b200-node", "NVIDIA-B200", 183359, 8),
        ])
        self.assertEqual(count, 1)
        self.assertEqual(viable[0].name, "b200-node")
        recipe["recommended_command"]["by_hardware"]["b200"] = "/different/model/hw/b200.json"
        with self.assertRaisesRegex(planner.PlannerError, "invalid-recipe-hardware"):
            planner.make_requirements("example/model", {}, recipe, "a" * 64, 32768)

    def test_exact_variant_hardware_takes_precedence_over_family_metadata(self):
        planner = load_planner()
        recipe = {
            "hf_id": "example/model",
            "variants": {"default": {"vram_minimum_gb": 32, "supported_hardware": ["b200"]}},
            "recommended_command": {"argv": ["vllm", "serve", "example/model", "--tensor-parallel-size", "1"]},
            "meta": {"hardware": {"gb300": "verified"}},
        }
        config = {"num_attention_heads": 24}
        requirements = planner.make_requirements("example/model", config, recipe, "a" * 64, 32768)
        count, viable = planner.choose_plan(requirements, config, [
            planner.NodeCapacity("b200-node", "NVIDIA-B200", 183359, 8),
            planner.NodeCapacity("gb300-node", "NVIDIA-GB300", 280000, 8),
        ])
        self.assertEqual(count, 1)
        self.assertEqual([node.name for node in viable], ["b200-node"])

    def test_unlabeled_gpu_node_does_not_block_verified_capacity(self):
        planner = load_planner()
        inventory = nodes()
        inventory["items"][0]["metadata"]["labels"].pop("nvidia.com/gpu.memory")
        responses = [
            subprocess.CompletedProcess([], 0, stdout=json.dumps(inventory)),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"items": []})),
        ]
        with mock.patch.object(planner.subprocess, "run", side_effect=responses):
            capacity = planner.inspect_cluster(time.monotonic() + 10)
        self.assertEqual([node.name for node in capacity], ["gpu-b"])
        self.assertEqual(capacity[0].memory_mib, 81920)

    def test_config_redirect_uses_only_pinned_same_origin_cache_endpoint(self):
        planner = load_planner()
        revision = "a" * 40
        config = {"num_attention_heads": 32}
        with mock.patch.object(planner, "bounded_json", side_effect=[
            ({"sha": revision}, b""),
            planner.PlannerError("metadata-redirect-disallowed"),
            (config, b""),
        ]) as fetch:
            self.assertEqual(
                planner.fetch_hf_inputs("example/model", "https://huggingface.co", 50.0, 1024),
                (revision, config),
            )
        self.assertEqual(fetch.call_args.args, (
            f"https://huggingface.co/api/resolve-cache/models/example/model/{revision}/config.json",
            50.0, 1024, "hermes-hf-gpu-planner/1",
        ))

    def test_config_policy_denial_uses_pinned_same_origin_cache_endpoint(self):
        planner = load_planner()
        revision = "a" * 40
        config = {"num_attention_heads": 32}
        with mock.patch.object(planner, "bounded_json", side_effect=[
            ({"sha": revision}, b""), planner.PlannerError("metadata-http-403"),
            (config, b""),
        ]) as fetch:
            self.assertEqual(
                planner.fetch_hf_inputs("example/model", "https://huggingface.co", 50.0, 1024),
                (revision, config),
            )
        self.assertEqual(fetch.call_args.args[0],
            f"https://huggingface.co/api/resolve-cache/models/example/model/{revision}/config.json")

    def test_config_authentication_failure_does_not_try_cache_endpoint(self):
        planner = load_planner()
        with mock.patch.object(planner, "bounded_json", side_effect=[
            ({"sha": "a" * 40}, b""), planner.PlannerError("metadata-http-401"),
        ]) as fetch:
            with self.assertRaisesRegex(planner.PlannerError, "metadata-http-401"):
                planner.fetch_hf_inputs("example/model", "https://huggingface.co", 50.0, 1024)
        self.assertEqual(fetch.call_count, 2)

    def test_config_cache_denial_stays_blocked(self):
        planner = load_planner()
        with mock.patch.object(planner, "bounded_json", side_effect=[
            ({"sha": "a" * 40}, b""), planner.PlannerError("metadata-http-403"),
            planner.PlannerError("metadata-http-403"),
        ]) as fetch:
            with self.assertRaisesRegex(planner.PlannerError, "metadata-http-403"):
                planner.fetch_hf_inputs("example/model", "https://huggingface.co", 50.0, 1024)
        self.assertEqual(fetch.call_count, 3)

    def test_config_cache_redirect_stays_blocked(self):
        planner = load_planner()
        with mock.patch.object(planner, "bounded_json", side_effect=[
            ({"sha": "a" * 40}, b""),
            planner.PlannerError("metadata-redirect-disallowed"),
            planner.PlannerError("metadata-redirect-disallowed"),
        ]) as fetch:
            with self.assertRaisesRegex(planner.PlannerError, "metadata-redirect-disallowed"):
                planner.fetch_hf_inputs("example/model", "https://huggingface.co", 50.0, 1024)
        self.assertEqual(fetch.call_count, 3)

    def run_planner(self, server: PlannerServer, node_payload: dict, pod_payload: dict, *extra: str, with_recipe: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.json").write_text(json.dumps(node_payload), encoding="utf-8")
            (root / "pods.json").write_text(json.dumps(pod_payload), encoding="utf-8")
            (root / "oc").write_text(
                "#!/bin/sh\ncase \"$*\" in *'get nodes'*) cat \"$PLAN_NODES\";; *'get pods'*) cat \"$PLAN_PODS\";; *) exit 9;; esac\n",
                encoding="utf-8",
            )
            (root / "oc").chmod(0o755)
            return subprocess.run(
                [
                    "python3", str(PLANNER), "--model", "example/model", "--namespace", "test", "--max-model-len", "4096",
                    "--api-base", server.url,
                    *(["--recipe-url", server.url + "/recipe.json"] if with_recipe else []), *extra,
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ | {"PATH": f"{root}:{os.environ['PATH']}", "PLAN_NODES": str(root / "nodes.json"), "PLAN_PODS": str(root / "pods.json")},
            )

    def test_exact_recipe_uses_whole_gpu_capacity_and_is_deterministic(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 120, "tensor_parallel_size": 2, "supported_gpu_products": ["H100"]}
        pods = {"items": [{"metadata": {"name": "busy"}, "spec": {"nodeName": "gpu-a", "containers": [{"resources": {"requests": {"nvidia.com/gpu": "1"}}}]}, "status": {"phase": "Running"}}]}
        with PlannerServer(metadata, {"num_attention_heads": 32, "num_key_value_heads": 8}, recipe) as server:
            result = self.run_planner(server, nodes(second=False), pods)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HF_GPU_PLAN_STATUS=ready", result.stdout)
        self.assertIn("HF_GPU_PLAN_SOURCE=official-vllm-recipe", result.stdout)
        self.assertIn("HF_GPU_SELECTED_NODE=gpu-a", result.stdout)
        self.assertIn("HF_GPU_COUNT=2", result.stdout)
        self.assertIn("HF_GPU_FREE_ON_NODE=3", result.stdout)
        self.assertIn("HF_GPU_VIABLE_NODE=gpu-a|NVIDIA-H100-80GB-HBM3|2|3", result.stdout)

    def test_current_official_catalog_recipe_shape_preserves_planner_outputs(self) -> None:
        recipe = {
            "hf_id": "example/model",
            "meta": {"hardware": {"h100": "verified", "b200": "verified"}},
            "recommended_command": {
                "argv": ["vllm", "serve", "example/model", "--tensor-parallel-size", "2"]
            },
            "variants": {"default": {"vram_minimum_gb": 120}},
        }
        with PlannerServer(
            {"sha": "a" * 40},
            {"num_attention_heads": 32},
            recipe,
        ) as server:
            result = self.run_planner(server, nodes(second=False), {"items": []})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HF_GPU_PLAN_SOURCE=official-vllm-recipe", result.stdout)
        self.assertIn("HF_GPU_REQUIRED_VRAM_GIB=120", result.stdout)
        self.assertIn("HF_GPU_COUNT=2", result.stdout)
        self.assertIn("HF_GPU_SELECTED_PRODUCT=NVIDIA-H100-80GB-HBM3", result.stdout)

    def test_rejects_checkpoint_only_sizing_missing_memory_invalid_topology_and_approval_drift(self) -> None:
        metadata = {"sha": "a" * 40, "siblings": [{"rfilename": "weights.safetensors", "size": 500_000_000_000}]}
        base_recipe = {"model": "example/model", "required_vram_gib": 120, "tensor_parallel_size": 2, "supported_gpu_products": ["H100"]}
        empty_pods = {"items": []}
        cases = (
            ({}, base_recipe, nodes(), "model-sizing-evidence-unavailable", False),
            ({"num_attention_heads": 3}, base_recipe, nodes(), "invalid-tensor-parallel-topology", True),
            ({"num_attention_heads": 32}, base_recipe, nodes(memory=""), "gpu-memory-label-missing", True),
        )
        for config, recipe, inventory, reason, with_recipe in cases:
            with self.subTest(reason=reason), PlannerServer(metadata, config, recipe) as server:
                result = self.run_planner(server, inventory, empty_pods, with_recipe=with_recipe)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HF_GPU_PLAN_STATUS=blocked", result.stdout)
            self.assertIn("HF_GPU_PLAN_REASON=" + reason, result.stdout)
        with PlannerServer(metadata, {"num_attention_heads": 32}, base_recipe) as server:
            result = self.run_planner(server, nodes(), empty_pods, "--approved-node", "gpu-b", "--approved-gpu-count", "2", "--approved-recipe-sha256", "0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=recipe-changed-after-confirmation", result.stdout)

    def test_no_recipe_approval_is_revalidated_and_detects_node_count_revision_drift(self) -> None:
        metadata = {"sha": "a" * 40}
        config = {"num_parameters": 10_000_000_000, "num_attention_heads": 32, "num_key_value_heads": 8,
                  "supported_gpu_products": ["H100"], "torch_dtype": "bfloat16", "hidden_size": 4096,
                  "num_hidden_layers": 32}
        approved = ("--approved-node", "gpu-a", "--approved-gpu-count", "1", "--approved-recipe-sha256", "unavailable")
        with PlannerServer(metadata, config, {}) as server:
            result = self.run_planner(server, nodes(), {"items": []}, *approved, with_recipe=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HF_GPU_RECIPE_SHA256=unavailable", result.stdout)
        for extra, reason in (( ("--approved-node", "gpu-b", "--approved-gpu-count", "1", "--approved-recipe-sha256", "unavailable"), "node-changed-after-confirmation"),
                              (("--approved-node", "gpu-a", "--approved-gpu-count", "2", "--approved-recipe-sha256", "unavailable"), "gpu-count-changed-after-confirmation"),
                              (("--expected-revision", "b" * 40), "revision-changed-after-confirmation")):
            with self.subTest(reason=reason), PlannerServer(metadata, config, {}) as server:
                result = self.run_planner(server, nodes(), {"items": []}, *extra, with_recipe=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HF_GPU_PLAN_REASON=" + reason, result.stdout)

    def test_readiness_taints_and_exact_ocs_toleration_are_enforced(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["H100"]}
        ocs = [{"key": "node.ocs.openshift.io/storage", "value": "true", "effect": "NoSchedule"}]
        for inventory, extra, reason in ((nodes(ready=False, second=False), (), "no-schedulable-gpu-nodes"),
                                         (nodes(taints=ocs, second=False), (), "no-schedulable-gpu-nodes"),
                                         (nodes(taints=[{"key": "other", "effect": "NoSchedule"}], second=False), ("--allow-ocs-storage-tainted-nodes",), "no-schedulable-gpu-nodes")):
            with self.subTest(reason=reason), PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
                result = self.run_planner(server, inventory, {"items": []}, *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HF_GPU_PLAN_REASON=" + reason, result.stdout)
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
            result = self.run_planner(server, nodes(taints=ocs, second=False), {"items": []}, "--allow-ocs-storage-tainted-nodes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_documented_preconfirmation_planner_propagates_ocs_toleration_opt_in(self) -> None:
        skill = (PLANNER.parent.parent / "SKILL.md").read_text(encoding="utf-8")
        section = skill[skill.index("Then run the bounded GPU/runtime planner before presenting a deployment plan."):]
        command_start = section.index("```sh") + len("```sh")
        command = section[command_start:section.index("```", command_start)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts" / "plan-hf-gpus.py"
            script.parent.mkdir()
            arguments = root / "planner-arguments"
            script.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" >\"$PLANNER_ARGUMENTS\"\nprintf '%s\\n' "
                "'HF_GPU_SELECTED_NODE=test-gpu-node' 'HF_GPU_COUNT=1' 'HF_GPU_RECIPE_SHA256=unavailable'\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            (root / "dynamo-defaults.yaml").write_text("allowOCSStorageTaintedNodes: true\n", encoding="utf-8")
            result = subprocess.run(
                ["sh", "-c", command], text=True, capture_output=True, check=False,
                env=os.environ | {
                    "SKILL_ROOT": str(root), "MODEL_ID": "example/model", "NAMESPACE": "test",
                    "MAX_MODEL_LEN": "4096", "VLLM_RECIPE_URL": "unavailable", "PLANNER_ARGUMENTS": str(arguments),
                },
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--allow-ocs-storage-tainted-nodes", arguments.read_text(encoding="utf-8").splitlines())

    def test_exact_hardware_classes_capacity_and_smallest_estimate(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["A10"]}
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
            result = self.run_planner(server, nodes(product="NVIDIA-A100-80GB"), {"items": []})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=incompatible-gpu-hardware", result.stdout)
        recipe["supported_gpu_products"] = ["H100"]
        recipe["required_vram_gib"] = 400
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
            result = self.run_planner(server, nodes(), {"items": []})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=insufficient-whole-gpu-capacity", result.stdout)
        estimate = {"num_parameters": 10_000_000_000, "num_attention_heads": 32, "num_key_value_heads": 8,
                    "supported_gpu_products": ["H100"], "torch_dtype": "bfloat16", "hidden_size": 4096,
                    "num_hidden_layers": 32}
        with PlannerServer(metadata, estimate, recipe) as server:
            result = self.run_planner(server, nodes(), {"items": []}, with_recipe=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HF_GPU_COUNT=1", result.stdout)

    def test_effective_pod_requests_include_restartable_init_sidecars(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["H100"]}
        pods = {"items": [{"spec": {"nodeName": "gpu-a", "containers": [{"resources": {"requests": {"nvidia.com/gpu": "5"}}}],
                                      "initContainers": [{"restartPolicy": "Always", "resources": {"requests": {"nvidia.com/gpu": "2"}}},
                                                         {"resources": {"requests": {"nvidia.com/gpu": "4"}}}]}, "status": {"phase": "Running"}}]}
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
            result = self.run_planner(server, nodes(second=False, gpu_count=7), pods)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=insufficient-whole-gpu-capacity", result.stdout)

    def test_invalid_or_time_bounded_remote_input_has_stable_error(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["H100"]}
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe) as server:
            result = self.run_planner(server, nodes(), {"items": []}, "--max-response-bytes", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=invalid-bound", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe, delay=0.07) as server:
            started = time.monotonic()
            result = self.run_planner(server, nodes(), {"items": []}, "--timeout-seconds", "0.1")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.35)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stdout, r"HF_GPU_PLAN_REASON=metadata-(unavailable|deadline-exceeded)")
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_and_oversized_json_have_stable_bounded_errors(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["H100"]}
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe, raw_payloads={"/api/models/example/model": b"{"}) as server:
            malformed = self.run_planner(server, nodes(), {"items": []})
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=invalid-metadata-json", malformed.stdout)
        self.assertNotIn("Traceback", malformed.stderr)
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe, raw_payloads={"/api/models/example/model": b"{" + b"x" * 128}, omit_content_length=True) as server:
            oversized = self.run_planner(server, nodes(), {"items": []}, "--max-response-bytes", "32")
        self.assertNotEqual(oversized.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=metadata-response-too-large", oversized.stdout)
        self.assertNotIn("Traceback", oversized.stderr)

    def test_dribbling_http_body_cannot_extend_total_deadline(self) -> None:
        metadata = {"sha": "a" * 40}
        recipe = {"model": "example/model", "required_vram_gib": 40, "tensor_parallel_size": 1, "supported_gpu_products": ["H100"]}
        with PlannerServer(metadata, {"num_attention_heads": 32}, recipe, dribble_interval=0.02) as server:
            started = time.monotonic()
            result = self.run_planner(server, nodes(), {"items": []}, "--timeout-seconds", "0.12")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.45, result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HF_GPU_PLAN_REASON=metadata-deadline-exceeded", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cluster_oc_calls_use_remaining_process_and_request_deadlines(self) -> None:
        planner = load_planner()
        completed = [
            subprocess.CompletedProcess(
                ["oc"], 0, json.dumps(nodes(second=False)), ""
            ),
            subprocess.CompletedProcess(["oc"], 0, json.dumps({"items": []}), ""),
        ]
        with mock.patch.object(
            planner.time, "monotonic", side_effect=[10.0, 11.0]
        ), mock.patch.object(
            planner.subprocess, "run", side_effect=completed
        ) as run:
            inventory = planner.inspect_cluster(15.0)

        self.assertEqual([item.name for item in inventory], ["gpu-a"])
        self.assertEqual(len(run.call_args_list), 2)
        for call in run.call_args_list:
            argv = call.args[0]
            request_timeout = next(
                value for value in argv if value.startswith("--request-timeout=")
            )
            self.assertRegex(request_timeout, r"^--request-timeout=[1-9][0-9]*ns$")
            request_nanoseconds = int(request_timeout.split("=", 1)[1][:-2])
            self.assertGreater(request_nanoseconds, 0)
            self.assertLessEqual(
                request_nanoseconds, int(call.kwargs["timeout"] * 1_000_000_000)
            )
            self.assertIs(call.kwargs["check"], False)
            self.assertIs(call.kwargs["capture_output"], True)
            self.assertIs(call.kwargs["text"], True)
        self.assertGreater(
            run.call_args_list[0].kwargs["timeout"],
            run.call_args_list[1].kwargs["timeout"],
        )

    def test_cluster_deadline_exhaustion_and_timeout_share_stable_reason(self) -> None:
        planner = load_planner()
        with mock.patch.object(planner.time, "monotonic", return_value=5.0), mock.patch.object(
            planner.subprocess, "run"
        ) as run:
            with self.assertRaisesRegex(
                planner.PlannerError, "cluster-inspection-deadline-exceeded"
            ):
                planner.inspect_cluster(5.0)
            run.assert_not_called()

        with mock.patch.object(planner.time, "monotonic", return_value=4.0), mock.patch.object(
            planner.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["oc"], 1.0),
        ):
            with self.assertRaisesRegex(
                planner.PlannerError, "cluster-inspection-deadline-exceeded"
            ):
                planner.inspect_cluster(5.0)

    def test_main_passes_one_absolute_deadline_from_metadata_to_cluster(self) -> None:
        planner = load_planner()
        requirement = planner.Requirements(
            40, 1, ("H100",), "model-config-estimate", "unavailable"
        )
        capacity = planner.NodeCapacity("gpu-a", "NVIDIA-H100-80GB-HBM3", 81920, 1)
        argv = [
            str(PLANNER),
            "--model", "example/model",
            "--namespace", "test",
            "--max-model-len", "4096",
            "--timeout-seconds", "15",
        ]
        with mock.patch.object(planner.sys, "argv", argv), mock.patch.object(
            planner.time, "monotonic", return_value=20.0
        ), mock.patch.object(
            planner, "fetch_hf_inputs", return_value=("a" * 40, {"num_attention_heads": 32})
        ) as fetch, mock.patch.object(
            planner, "make_requirements", return_value=requirement
        ), mock.patch.object(
            planner, "inspect_cluster", return_value=[capacity]
        ) as inspect, mock.patch.object(
            planner, "choose_plan", return_value=(1, [capacity])
        ):
            self.assertEqual(planner.main(), 0)

        metadata_deadline = fetch.call_args.args[2]
        cluster_deadline = inspect.call_args.args[0]
        self.assertEqual(metadata_deadline, 35.0)
        self.assertEqual(cluster_deadline, metadata_deadline)

    def test_chart_recipe_artifact_rejects_tamper_unknowns_oversize_and_symlink(self) -> None:
        planner = load_planner()
        artifact = chart_recipe_artifact()
        canonical = json.dumps(
            artifact, sort_keys=True, separators=(",", ":")
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_bytes(canonical)
            loaded = planner.load_recipe_artifact(
                valid,
                expected_model="example/model",
                expected_source="chart-owned:example-model-v1",
                expected_sha256=digest,
            )
            self.assertEqual(loaded, artifact)

            tampered = root / "tampered.json"
            tampered.write_bytes(canonical + b" ")
            with self.assertRaisesRegex(
                planner.PlannerError, "recipe-artifact-sha256-mismatch"
            ):
                planner.load_recipe_artifact(
                    tampered,
                    expected_model="example/model",
                    expected_source="chart-owned:example-model-v1",
                    expected_sha256=digest,
                )

            unknown_value = dict(artifact)
            unknown_value["command"] = "echo unsafe"
            unknown_bytes = json.dumps(
                unknown_value, sort_keys=True, separators=(",", ":")
            ).encode()
            unknown = root / "unknown.json"
            unknown.write_bytes(unknown_bytes)
            with self.assertRaisesRegex(
                planner.PlannerError, "invalid-chart-recipe-artifact"
            ):
                planner.load_recipe_artifact(
                    unknown,
                    expected_model="example/model",
                    expected_source="chart-owned:example-model-v1",
                    expected_sha256=hashlib.sha256(unknown_bytes).hexdigest(),
                )

            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * (planner.MAX_RECIPE_ARTIFACT_BYTES + 1))
            with self.assertRaisesRegex(
                planner.PlannerError, "recipe-artifact-too-large"
            ):
                planner.load_recipe_artifact(
                    oversized,
                    expected_model="example/model",
                    expected_source="chart-owned:example-model-v1",
                    expected_sha256="a" * 64,
                )

            linked = root / "linked.json"
            linked.symlink_to(valid)
            with self.assertRaisesRegex(
                planner.PlannerError, "recipe-artifact-symlink-disallowed"
            ):
                planner.load_recipe_artifact(
                    linked,
                    expected_model="example/model",
                    expected_source="chart-owned:example-model-v1",
                    expected_sha256=digest,
                )

    def test_chart_recipe_artifact_identity_mismatch_fails_closed(self) -> None:
        planner = load_planner()
        artifact = chart_recipe_artifact()
        canonical = json.dumps(
            artifact, sort_keys=True, separators=(",", ":")
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipe.json"
            path.write_bytes(canonical)
            for model, source, reason in (
                (
                    "other/model",
                    "chart-owned:example-model-v1",
                    "recipe-artifact-model-mismatch",
                ),
                (
                    "example/model",
                    "chart-owned:other",
                    "recipe-artifact-source-mismatch",
                ),
            ):
                with self.subTest(reason=reason), self.assertRaisesRegex(
                    planner.PlannerError, reason
                ):
                    planner.load_recipe_artifact(
                        path,
                        expected_model=model,
                        expected_source=source,
                        expected_sha256=digest,
                    )
