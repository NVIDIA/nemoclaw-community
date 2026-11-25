# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Setup and teardown resource tracking, tested against stateful CLI stubs."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parents[2]
MODEL_VOLUME = "local-only-workspace-assistant-ollama-models"
OLLAMA_CONTAINER = "local-only-workspace-assistant-ollama"

_DOCKER_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    set -eu
    S="$MOCK_CLI_DIR"
    next_ts() {
      n=0
      [ -f "$S/clock" ] && n="$(cat "$S/clock")"
      n=$((n + 1))
      printf '%s\\n' "$n" >"$S/clock"
      printf '2026-11-24T00:00:%02dZ' "$n"
    }
    case "${1:-}" in
      compose)
        shift
        if [ "${1:-}" = "version" ]; then
          echo "Docker Compose version v2.29.0"
          exit 0
        fi
        while [ "${1:-}" = "-f" ]; do shift 2; done
        case "${1:-}" in
          up)
            [ "${MOCK_FAIL_BEFORE_VOLUME:-0}" = "1" ] && exit 1
            if [ ! -d "$S/volumes/__MODEL_VOLUME__" ]; then
              mkdir -p "$S/volumes/__MODEL_VOLUME__/models"
              next_ts >"$S/volumes/__MODEL_VOLUME__/created_at"
            fi
            mkdir -p "$S/containers"
            : >"$S/containers/__OLLAMA_CONTAINER__"
            [ "${MOCK_FAIL_AFTER_VOLUME:-0}" = "1" ] && exit 1
            exit 0
            ;;
          down)
            rm -f "$S/containers/__OLLAMA_CONTAINER__"
            exit 0
            ;;
          exec)
            # exec -T ollama ollama show|pull <model>
            action="$5"
            model="$(printf '%s' "$6" | tr '/:' '__')"
            if [ "$action" = "show" ]; then
              [ -f "$S/volumes/__MODEL_VOLUME__/models/$model" ]
              exit $?
            fi
            mkdir -p "$S/volumes/__MODEL_VOLUME__/models"
            : >"$S/volumes/__MODEL_VOLUME__/models/$model"
            exit 0
            ;;
        esac
        ;;
      volume)
        case "${2:-}" in
          inspect)
            [ -d "$S/volumes/$3" ] || exit 1
            ts="$(cat "$S/volumes/$3/created_at")"
            printf '[{"Name":"%s","CreatedAt":"%s"}]\\n' "$3" "$ts"
            exit 0
            ;;
          rm)
            [ -d "$S/volumes/$3" ] || exit 1
            rm -rf "$S/volumes/$3"
            echo "$3"
            exit 0
            ;;
        esac
        ;;
      container)
        [ "${2:-}" = "inspect" ] && [ -f "$S/containers/$3" ] && exit 0
        exit 1
        ;;
      build)
        shift
        model=""
        base_url=""
        tag=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --build-arg)
              case "$2" in
                INFERENCE_MODEL=*) model="${2#INFERENCE_MODEL=}" ;;
                INFERENCE_BASE_URL=*) base_url="${2#INFERENCE_BASE_URL=}" ;;
              esac
              shift 2
              ;;
            -t) tag="$(printf '%s' "$2" | tr '/:' '__')"; shift 2 ;;
            *) shift ;;
          esac
        done
        mkdir -p "$S/images/$tag"
        printf '%s' "$model" >"$S/images/$tag/model"
        printf '%s' "$base_url" >"$S/images/$tag/base_url"
        exit 0
        ;;
      image)
        tag="$(printf '%s' "$3" | tr '/:' '__')"
        if [ "$2" = "inspect" ]; then
          [ -d "$S/images/$tag" ]
          exit $?
        fi
        rm -rf "$S/images/$tag"
        exit 0
        ;;
    esac
    echo "Unhandled docker stub: $*" >&2
    exit 99
    """
).replace("__MODEL_VOLUME__", MODEL_VOLUME).replace("__OLLAMA_CONTAINER__", OLLAMA_CONTAINER)

_OPENSHELL_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    set -eu
    S="$MOCK_CLI_DIR"
    case "${1:-}" in
      status)
        echo "Gateway Status: Ready"
        exit 0
        ;;
      profile)
        case "$2" in
          describe) [ -f "$S/profiles/$3" ]; exit $? ;;
          lint) exit 0 ;;
          import) mkdir -p "$S/profiles"; : >"$S/profiles/local-only-ollama"; exit 0 ;;
          delete) rm -f "$S/profiles/$3"; exit 0 ;;
        esac
        ;;
      provider)
        case "$2" in
          get) [ -f "$S/providers/$3" ]; exit $? ;;
          create)
            mkdir -p "$S/providers"
            # --name <n> --type <t>
            printf '%s' "$6" >"$S/providers/$4"
            exit 0
            ;;
          delete)
            rm -f "$S/providers/$3"
            exit 0
            ;;
        esac
        ;;
      sandbox)
        case "$2" in
          list)
            echo "NAME                PHASE"
            if [ -d "$S/sandboxes" ]; then
              for d in "$S/sandboxes"/*; do
                [ -d "$d" ] || continue
                printf '%s   %s\\n' "$(basename "$d")" "$(cat "$d/phase")"
              done
            fi
            exit 0
            ;;
          create)
            shift 2
            name=""
            image=""
            while [ $# -gt 0 ]; do
              case "$1" in
                --name) name="$2"; shift 2 ;;
                --from) image="$(printf '%s' "$2" | tr '/:' '__')"; shift 2 ;;
                *) shift ;;
              esac
            done
            rm -rf "$S/sandboxes/$name"
            mkdir -p "$S/sandboxes/$name/fs/sandbox/.openclaw"
            printf 'Ready' >"$S/sandboxes/$name/phase"
            model="$(cat "$S/images/$image/model")"
            base_url="$(cat "$S/images/$image/base_url")"
            cat >"$S/sandboxes/$name/fs/sandbox/.openclaw/openclaw.json" <<EOF
    {"agents":{"defaults":{"model":{"primary":"inference/$model"}}},"models":{"providers":{"inference":{"baseUrl":"$base_url"}}}}
    EOF
            exit 0
            ;;
          delete)
            rm -rf "$S/sandboxes/$3"
            exit 0
            ;;
          exec)
            # exec -n <name> --no-tty -- <cmd...>
            name="$4"
            shift 6
            fs="$S/sandboxes/$name/fs"
            args=""
            for arg in "$@"; do
              case "$arg" in
                /sandbox*) set -- "$@" "$fs$arg" ;;
                *) set -- "$@" "$arg" ;;
              esac
              shift
            done
            exec "$@"
            ;;
          upload)
            # upload --no-git-ignore <name> <src> <dst>
            fs="$S/sandboxes/$4/fs"
            mkdir -p "$(dirname "$fs$6")"
            cp "$5" "$fs$6"
            exit 0
            ;;
        esac
        ;;
      policy)
        if [ "$2" = "set" ]; then exit 0; fi
        cat <<'EOF'
    {"policy":{"version":1,"network_policies":{"_provider_local_only_ollama":{"endpoints":[{"host":"host.openshell.internal","port":11434}]}}}}
    EOF
        exit 0
        ;;
    esac
    echo "Unhandled openshell stub: $*" >&2
    exit 99
    """
)


class LifecycleScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name).resolve()
        self.recipe = self.base / "recipe"
        self.recipe.mkdir()
        for folder in ("scripts", "policies", "fixtures"):
            shutil.copytree(EXAMPLE_DIR / folder, self.recipe / folder)
        for filename in ("Dockerfile", "docker-compose.yml", "docker-compose.gpu.yml"):
            shutil.copyfile(EXAMPLE_DIR / filename, self.recipe / filename)
        os.symlink(EXAMPLE_DIR / "src", self.recipe / "src")

        self.bin_dir = self.base / "bin"
        self.bin_dir.mkdir()
        for name, body in (("docker", _DOCKER_STUB), ("openshell", _OPENSHELL_STUB)):
            stub = self.bin_dir / name
            stub.write_text(body, encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

        self.mock_dir = self.base / "mock"
        self.mock_dir.mkdir()

    def _precreate_volume(self, created_at: str = "2026-11-01T12:00:00Z") -> None:
        vol_dir = self.mock_dir / "volumes" / MODEL_VOLUME
        if vol_dir.exists():
            shutil.rmtree(vol_dir)
        (vol_dir / "models").mkdir(parents=True)
        (vol_dir / "created_at").write_text(created_at, encoding="utf-8")
        (vol_dir / "models" / "preexisting__model").write_text("", encoding="utf-8")

    def _volume_exists(self) -> bool:
        return (self.mock_dir / "volumes" / MODEL_VOLUME).is_dir()

    def _container_exists(self) -> bool:
        return (self.mock_dir / "containers" / OLLAMA_CONTAINER).is_file()

    def _created_entries(self) -> list[str]:
        created = self.recipe / ".run" / "created"
        if not created.exists():
            return []
        return [line for line in created.read_text(encoding="utf-8").splitlines() if line]

    def _run_script(
        self, script_name: str, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        python_dir = str(Path(sys.executable).resolve().parent)
        env["PATH"] = os.pathsep.join([str(self.bin_dir), python_dir, "/usr/bin", "/bin"])
        env["MOCK_CLI_DIR"] = str(self.mock_dir)
        env["INFERENCE_DEVICE"] = "cpu"
        env["ALLOW_MISSING_LANDLOCK"] = "1"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(self.recipe / "scripts" / script_name), *args],
            cwd=str(self.recipe),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            check=False,
        )

    def test_preexisting_volume_is_not_claimed_or_purged_after_second_setup(self) -> None:
        self._precreate_volume()

        first = self._run_script("bring-up.sh")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn("no record of creating it", first.stdout)
        self.assertFalse(any(item.startswith("volume=") for item in self._created_entries()))

        second = self._run_script("bring-up.sh")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertFalse(
            any(item.startswith("volume=") for item in self._created_entries()),
            self._created_entries(),
        )

        teardown = self._run_script("teardown.sh")
        self.assertEqual(teardown.returncode, 0, teardown.stdout)
        self.assertEqual(self._created_entries(), [])
        self.assertTrue(self._volume_exists())

        purge = self._run_script("teardown.sh", "--purge-models")
        self.assertEqual(purge.returncode, 0, purge.stdout)
        self.assertIn("Setup did not create volume", purge.stdout)
        self.assertTrue(self._volume_exists())
        self.assertTrue(
            (self.mock_dir / "volumes" / MODEL_VOLUME / "models" / "preexisting__model").is_file()
        )

    def test_preexisting_volume_is_not_purged_by_direct_purge_after_second_setup(self) -> None:
        self._precreate_volume()

        self.assertEqual(self._run_script("bring-up.sh").returncode, 0)
        self.assertEqual(self._run_script("bring-up.sh").returncode, 0)

        purge = self._run_script("teardown.sh", "--purge-models")
        self.assertEqual(purge.returncode, 0, purge.stdout)
        self.assertIn("Setup did not create volume", purge.stdout)
        self.assertTrue(self._volume_exists())
        self.assertFalse(self._container_exists())

    def test_recipe_created_volume_survives_normal_teardown_and_is_deleted_by_later_purge(self) -> None:
        first = self._run_script("bring-up.sh")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertNotIn("no record of creating it", first.stdout)
        self.assertTrue(any(item.startswith("volume=") for item in self._created_entries()))

        second = self._run_script("bring-up.sh")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertNotIn("no record of creating it", second.stdout)

        teardown = self._run_script("teardown.sh")
        self.assertEqual(teardown.returncode, 0, teardown.stdout)
        self.assertIn("The model volume is kept.", teardown.stdout)
        self.assertTrue(self._volume_exists())
        self.assertTrue(any(item.startswith("volume=") for item in self._created_entries()))

        third = self._run_script("bring-up.sh")
        self.assertEqual(third.returncode, 0, third.stdout)
        self.assertNotIn("no record of creating it", third.stdout)
        self.assertEqual(self._run_script("teardown.sh").returncode, 0)

        purge = self._run_script("teardown.sh", "--purge-models")
        self.assertEqual(purge.returncode, 0, purge.stdout)
        self.assertIn("Deleted the model volume", purge.stdout)
        self.assertFalse(self._volume_exists())
        self.assertEqual(self._created_entries(), [])

    def test_recreated_external_volume_with_same_name_is_not_purged(self) -> None:
        self.assertEqual(self._run_script("bring-up.sh").returncode, 0)
        self.assertEqual(self._run_script("teardown.sh").returncode, 0)

        # Replace the recipe-created volume outside the scripts with a new one.
        self._precreate_volume(created_at="2026-12-01T09:30:00Z")

        purge = self._run_script("teardown.sh", "--purge-models")
        self.assertEqual(purge.returncode, 0, purge.stdout)
        self.assertIn("Setup did not create volume", purge.stdout)
        self.assertTrue(self._volume_exists())
        self.assertEqual(self._created_entries(), [])

    def test_failed_compose_up_before_volume_creation_does_not_claim_later_external_volume(self) -> None:
        failed = self._run_script("bring-up.sh", extra_env={"MOCK_FAIL_BEFORE_VOLUME": "1"})
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(any(item.startswith("volume=") for item in self._created_entries()))

        self._precreate_volume()
        succeeded = self._run_script("bring-up.sh")
        self.assertEqual(succeeded.returncode, 0, succeeded.stdout)

        purge = self._run_script("teardown.sh", "--purge-models")
        self.assertEqual(purge.returncode, 0, purge.stdout)
        self.assertTrue(self._volume_exists())

    def test_absent_volume_clears_stale_record_on_normal_teardown(self) -> None:
        self.assertEqual(self._run_script("bring-up.sh").returncode, 0)
        shutil.rmtree(self.mock_dir / "volumes" / MODEL_VOLUME)

        teardown = self._run_script("teardown.sh")
        self.assertEqual(teardown.returncode, 0, teardown.stdout)
        self.assertEqual(self._created_entries(), [])

    def test_unowned_ollama_container_stops_setup_without_claiming_service(self) -> None:
        (self.mock_dir / "containers").mkdir(parents=True)
        (self.mock_dir / "containers" / OLLAMA_CONTAINER).write_text("", encoding="utf-8")

        result = self._run_script("bring-up.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(item == "compose=ollama" for item in self._created_entries()))


if __name__ == "__main__":
    unittest.main()
