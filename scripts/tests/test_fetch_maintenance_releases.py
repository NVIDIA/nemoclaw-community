# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for maintenance release snapshot fetching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.fetch_maintenance_releases import (
    GITHUB_API_ROOT,
    MaintenanceFetchError,
    build_snapshot,
    discover_nemoclaw_versions,
    fetch_latest_release,
    fetch_nemoclaw_stack,
    fetch_tag_channel,
    github_json,
    load_policy,
    normalize_checked_at,
    write_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]


def fixture_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "thresholds": {
            "dependency_warning_days": 30,
            "dependency_overdue_days": 60,
            "review_overdue_days": 120,
            "deprecation_days": 240,
        },
        "dependencies": {
            "zeta": {
                "label": "Zeta",
                "repository": "example/zeta",
                "source": "releases",
            },
            "alpha": {
                "label": "Alpha",
                "repository": "example/alpha",
                "source": "releases",
            },
        },
    }


class MaintenancePolicyTests(unittest.TestCase):
    def test_repository_policy_has_expected_registry(self) -> None:
        policy = load_policy(ROOT / "scripts/catalog-maintenance.json")

        self.assertEqual(
            (
                policy.dependency_warning_days,
                policy.dependency_overdue_days,
                policy.review_overdue_days,
                policy.deprecation_days,
            ),
            (30, 60, 120, 240),
        )
        self.assertEqual(
            {dependency.id: dependency.repository for dependency in policy.dependencies},
            {
                "hermes-agent": "NousResearch/hermes-agent",
                "nemoclaw": "NVIDIA/NemoClaw",
                "openclaw": "openclaw/openclaw",
                "openshell": "NVIDIA/OpenShell",
            },
        )
        nemoclaw = policy.dependencies_by_id["nemoclaw"]
        self.assertEqual((nemoclaw.source, nemoclaw.channel), ("tag-channel", "lkg"))

    def test_policy_rejects_invalid_values(self) -> None:
        cases = (
            (
                ("thresholds", "dependency_warning_days"),
                61,
                "thresholds must increase",
            ),
            (
                ("dependencies", "alpha", "label"),
                "**Alpha**",
                "invalid label",
            ),
            (
                ("dependencies", "alpha", "unexpected"),
                "value",
                "unsupported keys",
            ),
            (
                ("dependencies", "alpha", "source"),
                "branches",
                "source must be releases or tag-channel",
            ),
        )
        for keys, value, message in cases:
            with self.subTest(keys=keys), tempfile.TemporaryDirectory() as temp:
                policy = fixture_policy()
                target = policy
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                root = Path(temp)
                path = root / "scripts/catalog-maintenance.json"
                path.parent.mkdir()
                path.write_text(json.dumps(policy), encoding="utf-8")

                with self.assertRaisesRegex(MaintenanceFetchError, message):
                    load_policy(path)


class ReleaseFetchTests(unittest.TestCase):
    def test_nemoclaw_version_discovery_ignores_nested_manifests(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        example = root / "examples/recipes/community/sample"
        example.mkdir(parents=True)
        (example / "dependencies.toml").write_text(
            "schema_version = 1\n\n"
            "[stack]\n"
            'distribution = "nemoclaw"\n'
            'version = "v1.2.3"\n'
            'harness = "openclaw"\n',
            encoding="utf-8",
        )
        nested = example / "vendor/dependencies.toml"
        nested.parent.mkdir()
        nested.write_text("not valid TOML", encoding="utf-8")

        self.assertEqual(discover_nemoclaw_versions(root), {"v1.2.3"})

    def test_release_source_reads_latest_stable_release(self) -> None:
        payload = {
            "tag_name": "v2.0.0",
            "published_at": "2026-08-01T12:00:00Z",
            "html_url": "https://github.com/example/project/releases/tag/v2.0.0",
            "draft": False,
            "prerelease": False,
        }
        seen: list[tuple[str, str | None]] = []

        def get_json(url: str, token: str | None) -> object:
            seen.append((url, token))
            return payload

        result = fetch_latest_release("example/project", "token-value", get_json)

        self.assertEqual(
            seen,
            [
                (
                    f"{GITHUB_API_ROOT}/repos/example/project/releases/latest",
                    "token-value",
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "tag": "v2.0.0",
                "published_on": "2026-08-01",
                "url": "https://github.com/example/project/releases/tag/v2.0.0",
            },
        )

    def test_release_source_fails_when_no_stable_release_exists(self) -> None:
        def get_json(_url: str, _token: str | None) -> object:
            return {
                "tag_name": "v1.0.0-rc1",
                "published_at": "2026-08-01T12:00:00Z",
                "draft": False,
                "prerelease": True,
            }

        with self.assertRaisesRegex(
            MaintenanceFetchError, "did not return a published stable release"
        ):
            fetch_latest_release("example/project", None, get_json)

    def test_tag_channel_resolves_to_an_exact_stable_tag(self) -> None:
        sha = "a" * 40
        tag_object_sha = "b" * 40
        responses = {
            f"{GITHUB_API_ROOT}/repos/example/project/git/ref/tags/lkg": {
                "object": {"type": "commit", "sha": sha},
            },
            f"{GITHUB_API_ROOT}/repos/example/project/git/ref/tags/v1.2.3": {
                "object": {"type": "tag", "sha": tag_object_sha},
            },
            f"{GITHUB_API_ROOT}/repos/example/project/git/tags/{tag_object_sha}": {
                "tagger": {"date": "2026-08-10T15:00:00Z"},
                "object": {"type": "commit", "sha": sha},
            },
            f"{GITHUB_API_ROOT}/repos/example/project/commits/{sha}": {
                "sha": sha,
                "commit": {
                    "committer": {"date": "2026-08-05T23:15:00-04:00"},
                    "author": {"date": "2026-08-04T12:00:00Z"},
                },
            },
            f"{GITHUB_API_ROOT}/repos/example/project/tags?per_page=100": [
                {"name": "lkg", "commit": {"sha": sha}},
                {"name": "v1.2.3", "commit": {"sha": sha}},
            ],
        }

        result, resolved_sha = fetch_tag_channel(
            "example/project", "lkg", None, lambda url, _token: responses[url]
        )

        self.assertEqual(resolved_sha, sha)
        self.assertEqual(
            result,
            {
                "tag": "v1.2.3",
                "published_on": "2026-08-10",
                "url": "https://github.com/example/project/tree/v1.2.3",
            },
        )

    def test_nemoclaw_stack_comes_from_blueprint_and_agent_manifests(self) -> None:
        files = {
            "nemoclaw-blueprint/blueprint.yaml": (
                'min_openshell_version: "0.0.101"\n'
                'max_openshell_version: "0.0.101"\n'
            ),
            "agents/hermes/manifest.yaml": 'expected_version: "0.19.0"\n',
            "agents/openclaw/manifest.yaml": 'expected_version: "2026.7.1"\n',
        }
        with patch(
            "scripts.fetch_maintenance_releases.fetch_tag_commit",
            return_value=("b" * 40, None),
        ), patch(
            "scripts.fetch_maintenance_releases.fetch_repository_file",
            side_effect=lambda _repository, _revision, path, _token, _get_json: files[
                path
            ],
        ):
            stack = fetch_nemoclaw_stack("v0.0.109", None, lambda *_args: {})

        self.assertEqual(stack["openshell"], "0.0.101")
        self.assertEqual(stack["harnesses"]["hermes"], "0.19.0")
        self.assertEqual(stack["harnesses"]["openclaw"], "2026.7.1")

    def test_nemoclaw_stack_rejects_an_openshell_range(self) -> None:
        files = {
            "nemoclaw-blueprint/blueprint.yaml": (
                'min_openshell_version: "0.0.101"\n'
                'max_openshell_version: "0.0.116"\n'
            ),
            "agents/hermes/manifest.yaml": 'expected_version: "0.19.0"\n',
            "agents/openclaw/manifest.yaml": 'expected_version: "2026.7.1"\n',
        }
        with patch(
            "scripts.fetch_maintenance_releases.fetch_tag_commit",
            return_value=("b" * 40, None),
        ), patch(
            "scripts.fetch_maintenance_releases.fetch_repository_file",
            side_effect=lambda _repository, _revision, path, _token, _get_json: files[
                path
            ],
        ), self.assertRaisesRegex(MaintenanceFetchError, "cannot truthfully publish"):
            fetch_nemoclaw_stack("v0.0.109", None, lambda *_args: {})

    def test_snapshot_reuses_immutable_stacks_and_rejects_a_moved_tag(self) -> None:
        policy = load_policy(ROOT / "scripts/catalog-maintenance.json")
        stack = {
            "openshell": "0.0.85",
            "harnesses": {"hermes": "0.19.0", "openclaw": "2026.7.1"},
        }
        previous = {
            "v0.0.83": {"commit": "a" * 40, **stack},
            "v0.0.109": {"commit": "c" * 40, **stack},
        }
        release = {
            "tag": "v1.0.0",
            "published_on": "2026-08-01",
            "url": "https://github.com/example/project/releases/tag/v1.0.0",
        }

        patches = (
            patch(
                "scripts.fetch_maintenance_releases.fetch_latest_release",
                return_value=release,
            ),
            patch(
                "scripts.fetch_maintenance_releases.fetch_tag_channel",
                return_value=(
                    {
                        "tag": "v0.0.109",
                        "published_on": "2026-08-14",
                        "url": "https://github.com/NVIDIA/NemoClaw/tree/v0.0.109",
                    },
                    "c" * 40,
                ),
            ),
            patch(
                "scripts.fetch_maintenance_releases.fetch_component_version",
                return_value="1.0.0",
            ),
            patch(
                "scripts.fetch_maintenance_releases.discover_nemoclaw_versions",
                return_value={"v0.0.83"},
            ),
            patch("scripts.fetch_maintenance_releases.fetch_nemoclaw_stack"),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4] as fetch_stack, patch(
            "scripts.fetch_maintenance_releases.fetch_tag_commit",
            return_value=("a" * 40, None),
        ):
            snapshot = build_snapshot(
                policy,
                "2026-08-31T00:00:00Z",
                root=ROOT,
                previous_stacks=previous,
            )

        self.assertEqual(snapshot["nemoclaw_stacks"], previous)
        fetch_stack.assert_not_called()

        with patches[0], patches[1], patches[2], patches[3], patch(
            "scripts.fetch_maintenance_releases.fetch_tag_commit",
            return_value=("b" * 40, None),
        ), self.assertRaisesRegex(MaintenanceFetchError, "tag v0.0.83 moved"):
            build_snapshot(
                policy,
                "2026-08-31T00:00:00Z",
                root=ROOT,
                previous_stacks=previous,
            )

    def test_snapshot_is_sorted_and_checked_at_is_normalized(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        policy_path = root / "policy.json"
        policy_path.write_text(json.dumps(fixture_policy()), encoding="utf-8")
        policy = load_policy(policy_path)

        def get_json(url: str, _token: str | None) -> object:
            repository = "alpha" if "/example/alpha/" in url else "zeta"
            return {
                "tag_name": "v1.0.0",
                "published_at": "2026-08-01T12:00:00Z",
                "html_url": (
                    f"https://github.com/example/{repository}/releases/tag/v1.0.0"
                ),
                "draft": False,
                "prerelease": False,
            }

        snapshot = build_snapshot(
            policy,
            "2026-08-31T10:30:12-04:00",
            get_json=get_json,
        )

        self.assertEqual(snapshot["checked_at"], "2026-08-31T14:30:12Z")
        self.assertEqual(list(snapshot["releases"]), ["alpha", "zeta"])
        self.assertEqual(
            set(snapshot["releases"]["alpha"]),
            {"tag", "component_version", "published_on", "url"},
        )

        output = root / "snapshot.json"
        write_snapshot(output, snapshot)
        first = output.read_bytes()
        write_snapshot(output, snapshot)
        self.assertEqual(output.read_bytes(), first)
        self.assertEqual(json.loads(first)["checked_at"], snapshot["checked_at"])

    def test_checked_at_requires_timezone(self) -> None:
        with self.assertRaisesRegex(MaintenanceFetchError, "include a timezone"):
            normalize_checked_at("2026-08-31T10:30:12")


class GitHubClientTests(unittest.TestCase):
    def test_client_sets_token_without_exposing_it_in_url(self) -> None:
        class Response:
            headers: dict[str, str] = {}

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return b'{"ok": true}'

        with patch(
            "scripts.fetch_maintenance_releases.urlopen", return_value=Response()
        ) as mocked_urlopen:
            self.assertEqual(
                github_json("https://api.github.com/example", "secret-token"),
                {"ok": True},
            )

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertNotIn("secret-token", request.full_url)


if __name__ == "__main__":
    unittest.main()
