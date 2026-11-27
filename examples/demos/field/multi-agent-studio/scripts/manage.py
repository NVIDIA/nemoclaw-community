#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0

"""Advanced host/development commands, exposed through ./bac dev."""
import argparse
import json
import platform
import shutil
import subprocess
import sys

import ops_common as c
import ops_deploy as app
import ops_llm as llm
import ops_runtime as runtime


def seconds(value):
    number = int(value)
    if not 0 <= number <= 3600:
        raise argparse.ArgumentTypeError('Use a wait between 0 and 3600 seconds.')
    return number


def port_number(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError('Use an application port between 1024 and 65535.')
    return number


def setup_stack(model=None):
    if model:
        llm.require_spark()
    print('1/2 · Install or reuse the agent runtime.', flush=True)
    runtime.setup()
    if model:
        print('2/2 · Install or reuse the shared model. Weights download only during setup.', flush=True)
        llm.setup(model)
    else:
        print('2/2 · Use your existing model endpoint; no weights downloaded.')
    next_command = './bac dev start --model ' + (model or 'external') if c.systemd_available() else './bac dev preview'
    print('Setup complete. Next: ' + next_command + ', then connect the model in Settings.')


def start_stack(args):
    # Fail on checkout/port/install problems before warming a large model.
    app.validate_start(args.host, args.port)
    runtime.require_installed()
    model = args.model or c.read_json(c.home() / 'llm.json', {}).get('profile')
    if model == 'external':
        model = None
    if model:
        print('1/3 · Start or reuse ' + model + '.', flush=True)
        llm.start(model)
        llm.check(args.wait)
    else:
        print('1/3 · Using your existing endpoint. Connect it in Settings → Model.')
    print('2/3 · Start or reuse OpenClaw.', flush=True)
    runtime.start()
    runtime.check(wait=45)
    print('3/3 · Start or reuse the app.', flush=True)
    app.start(args.host, args.port)
    print('Open http://localhost:' + str(app.settings()['port']) + ' → Settings → Model → Connect.')
    if model:
        print('Local endpoint: http://127.0.0.1:8000/v1 · model: bac-local')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='./bac dev', description='Multi-Agent Studio: setup once, start the studio, update the app independently from the model.',
                                     epilog='Foreground preview: ./bac dev preview. Existing model: ./bac dev setup, then ./bac dev start --model external. Foreground/UI preview: ./bac dev preview')
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('setup', help='Install OpenClaw; optionally install a shared Spark model')
    setup.add_argument('--model', choices=['qwen', 'gemma'], help='Omit to use an existing local or hosted model endpoint')
    start = commands.add_parser('start', help='Start the installed services; keep healthy running services in place')
    start.add_argument('--model', choices=['external', 'qwen', 'gemma'], help='external leaves model servers alone; otherwise defaults to the last managed model')
    start.add_argument('--wait', type=seconds, default=600, help='Wait up to this many seconds for the model (default: 600)')
    start.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'])
    start.add_argument('--port', type=port_number)
    for name, help_text in [('doctor','Inspect this host and show the next setup step'),('status','Show managed services and data location'),
                            ('update','Update the app without replacing the model'),('rollback','Restore the previous app release')]:
        commands.add_parser(name, help=help_text)
    application = commands.add_parser('app').add_subparsers(dest='action', required=True)
    start = application.add_parser('start')
    start.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'])
    start.add_argument('--port', type=port_number)
    for name in ('stop', 'logs'):
        application.add_parser(name)
    model = commands.add_parser('llm').add_subparsers(dest='action', required=True)
    for name in ('plan', 'setup', 'start', 'remove'):
        command = model.add_parser(name)
        command.add_argument('model', choices=['qwen', 'gemma'])
        if name == 'remove':
            command.add_argument('--yes', action='store_true')
    for name in ('stop', 'check', 'logs', 'remove-runtime'):
        command = model.add_parser(name)
        if name == 'check':
            command.add_argument('--wait', type=seconds, default=0, help='Wait for model startup, in seconds')
        if name == 'remove-runtime':
            command.add_argument('--yes', action='store_true')
    agent = commands.add_parser('runtime').add_subparsers(dest='action', required=True)
    for name in ('setup', 'start', 'stop', 'check', 'logs'):
        command = agent.add_parser(name)
        if name == 'check':
            command.add_argument('--wait', type=seconds, default=0)
    agent.add_parser('preflight').add_argument('--protected', action='store_true')
    shell = commands.add_parser('openshell').add_subparsers(dest='action', required=True)
    for name in ('enable', 'check', 'prove'):
        shell.add_parser(name)
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        parser.print_help()
        return
    args = parser.parse_args(arguments)
    if args.command in ('setup', 'start'):
        with c.locked():
            if args.command == 'setup':
                setup_stack(args.model)
            else:
                start_stack(args)
        return
    if args.command in ('runtime', 'openshell'):
        if args.command == 'runtime' and args.action == 'preflight':
            from runtime_preflight import run
            run(args.protected)
        elif args.command == 'runtime' and args.action == 'check':
            runtime.check(args.wait)
        elif args.command == 'runtime' and args.action == 'logs':
            c.run(['journalctl', '--user', '-u', 'bac-openclaw', '-n', '100', '--no-pager'])
        else:
            with c.locked():
                if args.command == 'openshell':
                    runtime.openshell(args.action)
                elif args.action == 'setup':
                    runtime.setup()
                elif args.action == 'start':
                    runtime.start()
                elif args.action == 'stop':
                    c.require_idle()
                    c.service('bac-openclaw', 'stop')
        return
    if args.command == 'doctor':
        print('Host:', platform.system(), platform.machine())
        for tool in ('git', 'python3', 'nvidia-smi', 'ffmpeg', 'uv', 'systemctl', 'docker', 'openshell', 'ssh', 'pdftotext', 'pdfinfo'):
            print(tool + ':', shutil.which(tool) or 'not found')
        print('systemd user session:', 'available' if c.systemd_available() else 'unavailable')
        print('Data directory:', c.home())
        print('uv can be bootstrapped locally during setup; OS packages/drivers are not installed by ./bac.')
        if platform.system() == 'Linux':
            print('App/OpenClaw prerequisites: git, Python 3.9+, a systemd user session. PDF uploads: poppler-utils.')
            print('Fresh Spark: ./bac dev setup --model qwen → ./bac dev start --model qwen')
            print('Existing model endpoint: ./bac dev setup → ./bac dev start --model external → Settings → Model')
            print('Without a systemd user session or with copied/edited source: ./bac dev setup → ./bac dev preview')
        else:
            print('On this host: ./bac dev setup → ./bac dev preview → Settings → Model')
        return
    if args.command == 'status':
        app.status()
        return
    if args.command == 'llm' and args.action == 'plan':
        command, spec = llm.command(args.model)
        print(json.dumps({'python': llm.profiles()['python'], 'packages': llm.profiles()['packages'],
                          'model': spec['id'], 'revision': spec['revision'],
                          'environment': llm.profiles()['environment'], 'command': command}, indent=2))
        return
    if args.command == 'llm' and args.action == 'check':
        llm.check(args.wait)
        return
    if args.command in ('app', 'llm') and args.action == 'logs':
        c.require_systemd()
        c.run(['journalctl', '--user', '-u', 'bac-demo' if args.command == 'app' else 'bac-llm', '-n', '100', '--no-pager'])
        return
    with c.locked():
        if args.command == 'update':
            app.update()
        elif args.command == 'rollback':
            app.rollback()
        elif args.command == 'app':
            if args.action == 'start':
                app.start(args.host, args.port)
            else:
                c.require_idle()
                c.service('bac-demo', 'stop')
        elif args.action == 'setup':
            llm.setup(args.model)
        elif args.action == 'start':
            llm.start(args.model)
        elif args.action == 'remove':
            llm.remove(args.model, args.yes)
        elif args.action == 'remove-runtime':
            llm.remove_runtime(args.yes)
        elif args.action == 'stop':
            c.require_idle()
            c.service('bac-llm', 'stop')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Multi-Agent Studio:', error, file=sys.stderr)
        sys.exit(1)
