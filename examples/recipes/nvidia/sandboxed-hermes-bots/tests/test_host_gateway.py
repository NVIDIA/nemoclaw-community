# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Host lifecycle regressions with isolated state and no real Hermes processes."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HostGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-host-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes_home = self.root / "home" / ".hermes"
        self.hermes_home.mkdir(parents=True)
        (self.hermes_home / "active_profile").write_text("work\n")

    def run_shell(self, script, *, listing="", state=None, returncode=0):
        if state is not None:
            (self.hermes_home / "gateway_state.json").write_text(json.dumps(state))
        env = dict(os.environ, HOME=str(self.hermes_home.parent),
                   SWARM_ROOT=str(ROOT), SWARM_STATE=str(self.root / "state"),
                   GATEWAY_LISTING=listing, GATEWAY_RC=str(returncode),
                   GATEWAY_EVENTS=str(self.root / "events"),
                   TZ="UTC", LC_ALL="C", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            ["bash", "-c", '''
set -euo pipefail
source "$SWARM_ROOT/lib/common.sh"
source "$SWARM_ROOT/lib/host.sh"
hermes() {
  [[ "$*" == '-p default gateway list' ]] || return 67
  printf '%s\n' "$GATEWAY_LISTING"
  return "$GATEWAY_RC"
}
sleep() { :; }
kill() { printf 'unexpected kill: %s\n' "$*" >> "$GATEWAY_EVENTS"; }
''' + script], env=env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_uses_verified_default_pid_instead_of_runtime_state(self):
        listing = "Gateways:\n  ✓ default (current) — PID 4242\n  ✓ work — PID 9999"
        self.assertEqual(self.run_shell("host_gateway_pid", listing=listing,
                                       state={"pid": os.getpid()}), "4242")

    def test_missing_null_nonpositive_and_reused_runtime_pids_are_ignored(self):
        for state in ({}, {"pid": None}, {"pid": 0}, {"pid": -1},
                      {"pid": os.getpid(), "gateway_state": "stopped"}):
            with self.subTest(state=state):
                self.assertEqual(self.run_shell("host_gateway_pid", state=state,
                                               listing="Gateways:\n  ✗ default — not running"), "")

    def test_rejects_other_profiles_and_invalid_reported_pids(self):
        for listing in ("✓ work — PID 4242", "✓ default-other — PID 4242",
                        "✓ default — PID 0", "✓ default — PID -2",
                        "✓ default — PID nope", "Unable to list profiles."):
            with self.subTest(listing=listing):
                self.assertEqual(self.run_shell("host_gateway_pid", listing=listing), "")

    def test_failed_lookup_does_not_accept_partial_output(self):
        self.assertEqual(self.run_shell("if host_gateway_running; then echo yes; else echo no; fi",
                                       listing="✓ default — PID 4242", returncode=1), "no")

    def test_ansi_colored_default_pid(self):
        self.assertEqual(self.run_shell("host_gateway_pid",
                                       listing="  ✓ \x1b[32mdefault\x1b[0m (current) — PID 4242"), "4242")

    def test_start_selects_default_despite_persisted_work_profile(self):
        script = '''
hermes() {
  case "$*" in
    '-p default gateway list')
      if [[ -f "$GATEWAY_EVENTS" ]]; then printf '  ✓ default (current) — PID 4242\n'; fi ;;
    '-p default gateway run') printf '%s\n' "$*" > "$GATEWAY_EVENTS" ;;
    *) return 67 ;;
  esac
}
daemonize() { shift; "$@"; }
host_gateway_ensure >/dev/null
cat "$GATEWAY_EVENTS"
'''
        self.assertEqual(self.run_shell(script), "-p default gateway run")
        self.assertEqual((self.hermes_home / "active_profile").read_text(), "work\n")

    def test_failed_lookup_does_not_launch_another_gateway(self):
        self.assertEqual(self.run_shell('''
daemonize() { printf 'unexpected start\n' > "$GATEWAY_EVENTS"; }
if host_gateway_ensure >/dev/null; then echo started; else echo failed; fi
[[ ! -e "$GATEWAY_EVENTS" ]]
''', returncode=1), "failed")

    def test_stop_delegates_identity_validation_without_signaling_saved_pid(self):
        script = '''
hermes() {
  case "$*" in
    '-p default gateway stop') printf '%s\n' "$*" >> "$GATEWAY_EVENTS" ;;
    '-p default gateway list') printf '  ✗ default — not running\n' ;;
    *) return 67 ;;
  esac
}
host_gateway_stop
cat "$GATEWAY_EVENTS"
'''
        for state in ({"pid": os.getpid()}, {"pid": None}, {"pid": 0}):
            with self.subTest(state=state):
                (self.root / "events").unlink(missing_ok=True)
                self.assertEqual(self.run_shell(script, state=state), "-p default gateway stop")

    def test_stop_failure_is_reported_without_raw_kill_fallback(self):
        self.assertEqual(self.run_shell('''
hermes() { return 1; }
if host_gateway_stop >/dev/null; then echo stopped; else echo failed; fi
[[ ! -e "$GATEWAY_EVENTS" ]]
''', state={"pid": os.getpid()}), "failed")

    def test_still_running_after_stop_is_reported_without_raw_kill(self):
        self.assertEqual(self.run_shell('''
hermes() {
  [[ "$*" != '-p default gateway list' ]] || printf '✓ default — PID 4242\n'
  return 0
}
if host_gateway_stop >/dev/null; then echo stopped; else echo failed; fi
[[ ! -e "$GATEWAY_EVENTS" ]]
''', state={"pid": os.getpid()}), "failed")

    def test_failed_post_stop_lookup_is_not_success(self):
        self.assertEqual(self.run_shell('''
hermes() { [[ "$*" == '-p default gateway stop' ]]; }
if host_gateway_stop >/dev/null; then echo stopped; else echo failed; fi
[[ ! -e "$GATEWAY_EVENTS" ]]
'''), "failed")

    def test_hook_cleanup_does_not_restart_after_failed_stop(self):
        self.assertEqual(self.run_shell('''
mkdir -p "$HOME/.hermes/profiles/bot/plugins/dropbox"
hermes() { return 0; }
host_gateway_running() { return 0; }
host_gateway_stop() { return 1; }
host_gateway_ensure() { printf 'unexpected restart\n' > "$GATEWAY_EVENTS"; }
if host_dropbox_remove bot >/dev/null; then echo cleaned; else echo failed; fi
[[ ! -e "$GATEWAY_EVENTS" ]]
'''), "failed")

    def test_legacy_names_are_removable_but_not_creatable(self):
        for name in ("bad--name", "bad-", "overlong-name-for-openshell"):
            with self.subTest(name=name):
                self.assertEqual(self.run_shell(f'''
SANDBOX_PREFIX=test-
valid_name_loose '{name}'
if valid_name '{name}'; then echo accepted; else echo refused; fi
'''), "refused")

    def test_removal_still_rejects_unsafe_path_components(self):
        for name in ("../x", "a/b", "", "-flag", "a b", "UPPER"):
            with self.subTest(name=name):
                self.assertEqual(self.run_shell(f'''
if valid_name_loose '{name}'; then echo accepted; else echo refused; fi
'''), "refused")

    def test_rm_command_passes_legacy_name_to_scoped_teardown(self):
        for name in ("bad--name", "bad-", "overlong-name-for-openshell"):
            with self.subTest(name=name):
                self.assertEqual(self.run_shell(f'''
source <(sed -n '/^cmd_rm()/,/^}}/p' "$SWARM_ROOT/swarm")
bot_destroy_scope() {{ printf 'removed:%s\\n' "$1"; }}
cmd_rm '{name}' --yes
'''), "removed:" + name)

    def test_live_gateway_check_excludes_explicit_default_profile(self):
        check_line = next(line for line in (ROOT / "tests" / "e2e.sh").read_text().splitlines()
                          if 'check "no per-profile gateways"' in line)
        script = '''
HOST_GATEWAY=on
check() { printf '%s\n' "$2"; }
hermes() {
  [[ "$*" == '-p default gateway list' ]] || return 67
  printf '✓ default (current) — PID 123\n✓ work — PID 456\n✓ served — served by the default multiplexer\n'
}
'''
        self.assertEqual(self.run_shell(script + check_line), "1")


if __name__ == "__main__":
    unittest.main()
