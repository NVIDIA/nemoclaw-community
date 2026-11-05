# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the service handoff with fake local commands, never a real gateway."""

import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-brev-gateway.sh"


class BrevGatewayHandoffTest(unittest.TestCase):
    def run_handoff(self, result, database=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            tls = root / "tls"
            tls.mkdir()
            (tls / "ca.crt").touch()
            state = root / "state"
            state.mkdir()
            if database == "invalid":
                (state / "openshell.db").write_text("not a database")
            elif database is not None:
                with sqlite3.connect(state / "openshell.db") as connection:
                    connection.execute("CREATE TABLE objects (object_type TEXT)")
                    connection.executemany(
                        "INSERT INTO objects VALUES (?)", [("Sandbox",)] * database
                    )
            management = root / "gateway-management.env"
            management.write_text(
                "NEMOCLAW_GATEWAY_PORT=18080\n"
                "NEMOCLAW_OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:18080\n"
                f"NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR={state}\n"
                f"OPENSHELL_LOCAL_TLS_DIR={tls}\n"
            )
            script = root / "handoff.sh"
            script.write_text(SCRIPT.read_text().replace(
                'MANAGEMENT_ENV="/etc/nemoclaw/gateway-management.env"',
                f'MANAGEMENT_ENV="{management}"',
            ))
            fakes = {
                "systemctl": 'test -f "$TEST_ROOT/stopped" && echo inactive || echo active',
                "sudo": '''if [[ "$1" == -n ]]; then shift; fi
if [[ "$1" == python3 ]]; then exec "$@"; fi
printf '%s\\n' "$*" >> "$TEST_ROOT/service-calls"
touch "$TEST_ROOT/stopped"''',
                "openshell": '''printf '%s\n' "$*" >> "$TEST_ROOT/gateway-calls"
if [[ "$1" == gateway && "$2" == remove ]]; then exit 0; fi
if [[ "$1" != --gateway-endpoint || "$2" != https://127.0.0.1:18080 ]]; then
  echo 'Wrong gateway inspected' >&2; exit 9
fi
case "$TEST_GATEWAY_RESULT" in
  empty) echo 'No sandboxes found.' ;;
  occupied) echo 'NAME STATUS'; echo 'existing Ready' ;;
  unreachable) echo 'Connection refused' >&2; exit 1 ;;
esac
''',
            }
            for name, body in fakes.items():
                path = commands / name
                path.write_text("#!/bin/bash\n" + body + "\n")
                path.chmod(0o755)
            env = {
                "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                "HOME": str(root),
                "OPENSHELL_BIN": str(commands / "openshell"),
                "TEST_ROOT": str(root),
                "TEST_GATEWAY_RESULT": result,
                # A stale ambient gateway must not determine which host is checked.
                "OPENSHELL_GATEWAY": "stale-registration",
                "NEMOCLAW_GATEWAY_ENDPOINT": "https://127.0.0.1:8080",
            }
            process = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
            calls = (root / "gateway-calls").read_text()
            stopped = (root / "stopped").exists()
            return process, calls, stopped

    def test_empty_declared_gateway_can_be_retired(self):
        process, calls, stopped = self.run_handoff("empty")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(stopped)
        self.assertIn("--gateway-endpoint https://127.0.0.1:18080 sandbox list", calls)
        self.assertIn("gateway remove nemoclaw", calls)

    def test_nonempty_gateway_service_is_preserved(self):
        process, calls, stopped = self.run_handoff("occupied")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(stopped)
        self.assertNotIn("gateway remove", calls)

    def test_unreachable_gateway_service_is_preserved(self):
        process, calls, stopped = self.run_handoff("unreachable")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(stopped)
        self.assertNotIn("gateway remove", calls)

    def test_unreachable_gateway_with_empty_database_can_be_retired(self):
        process, calls, stopped = self.run_handoff("unreachable", database=0)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(stopped)
        self.assertIn("gateway remove nemoclaw", calls)

    def test_unreachable_gateway_with_occupied_or_invalid_database_is_preserved(self):
        for database in (1, "invalid"):
            with self.subTest(database=database):
                process, calls, stopped = self.run_handoff("unreachable", database)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(stopped)
                self.assertNotIn("gateway remove", calls)


if __name__ == "__main__":
    unittest.main()
