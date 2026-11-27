# SPDX-License-Identifier: Apache-2.0

"""Stop a service still owned by this installation of the retired model launcher."""
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def stop(root):
    directory = root / '.local-model'
    record = directory / 'state.json'
    if not record.is_file():
        return
    with (directory / 'operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not record.is_file():
            return
        state = json.loads(record.read_text())
        unit = 'bac-studio-llm-' + hashlib.sha256(str(root).encode()).hexdigest()[:12] + '.service'
        if state.get('unit') == unit and state.get('invocation_id'):
            result = subprocess.run(
                ['systemctl', '--user', 'show', unit, '--property=InvocationID,LoadState'],
                capture_output=True, text=True, timeout=10)
            properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            if properties.get('LoadState') != 'not-found':
                result.check_returncode()
                if properties.get('InvocationID') == state['invocation_id']:
                    subprocess.run(['systemctl', '--user', 'stop', unit], check=True, timeout=75)
                    print('Stopped the local model started by the previous Multi-Agent Studio launcher.')
        record.unlink()
        (directory / 'attempt.json').unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        stop(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'Could not complete legacy model cleanup: {error}')
