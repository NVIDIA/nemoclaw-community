#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0

"""Record sandbox ownership at creation, before the native registry can be lost."""
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys


def creation_args(args, agent_id, config, database):
    boundary = args.index('--') if '--' in args else len(args)
    if not any(args[i:i+2] == ['sandbox', 'create'] for i in range(boundary-1)):
        return args
    if not isinstance(agent_id,str) or not re.fullmatch(r'bac-[a-f0-9]{24}(?:-r[0-9]+)?',agent_id) or agent_id not in config.get('agents',{}).get('entries',{}):
        raise RuntimeError('Sandbox creation has no unique active Multi-Agent Studio owner.')
    with sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro', uri=True) as db:
        if '-r' in agent_id:
            # Preserved crew identities may predate the account-owned team.
            # Their native ID prefix is not an ownership record.
            rows = db.execute('''SELECT a.deleting FROM crew_resources r
                JOIN agents a ON a.id=r.owner AND a.kind='crew'
                WHERE r.native_id=?''', (agent_id,)).fetchall()
        else:
            rows = db.execute("SELECT deleting,profile FROM agents WHERE id=? AND kind='personal'",
                              (agent_id[4:],)).fetchall()
            rows = [row for row in rows if json.loads(row[1] or '{}').get('id') == agent_id]
    if len(rows) != 1:
        raise RuntimeError('Sandbox creation has no unique active Multi-Agent Studio owner.')
    if rows[0][0]:raise RuntimeError('Agent deletion has started; sandbox creation is blocked.')
    # The backend persists this label with the resource, not after CLI success.
    return args[:boundary]+['--label', 'bac-agent-id='+agent_id]+args[boundary:]


def main():
    import agent_runtime as runtime
    import ops_common
    from openshell_runtime import command as pinned_command
    command = pinned_command()
    if not command or Path(command).resolve() == Path(__file__).resolve():
        raise RuntimeError('The OpenShell executable is unavailable.')
    args = sys.argv[1:]
    boundary=args.index('--') if '--' in args else len(args)
    if any(args[i:i+2]==['sandbox','create'] for i in range(boundary-1)) and '--name' in args[:boundary]:
        name=args[args.index('--name')+1]
        # Native context registers its lazy backend before CLI creation. Resolve
        # that exact runtime name; the plugin SDK does not reliably forward cwd.
        result=subprocess.run([str(runtime.root()/'node/bin/node'),str(Path(__file__).with_name('sandbox_registry.mjs')),
                               str(runtime.root()),'--owner',name],env=runtime.environment(),capture_output=True,text=True,timeout=15,check=True)
        owner=json.loads(result.stdout)['agentId']
        config = json.loads(runtime.config_path().read_text())
        args = creation_args(args, owner, config, ops_common.home()/'studio/studio.sqlite')
    from openshell_runtime import environment
    os.execve(command, [command, *args], environment())


if __name__ == '__main__':
    try:main()
    except Exception as error:
        print('Multi-Agent Studio sandbox ownership check failed ('+type(error).__name__+'). Creation was not sent.', file=sys.stderr)
        sys.exit(1)
