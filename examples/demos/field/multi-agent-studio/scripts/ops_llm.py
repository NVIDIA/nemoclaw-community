# SPDX-License-Identifier: Apache-2.0

"""Install and operate one shared, separately managed vLLM endpoint."""
import hashlib
import json
import os
import platform
import shutil
import sys
import urllib.request

import ops_common as c

KERNEL_CHECK = '''import torch
from vllm.utils.flashinfer import has_flashinfer_b12x_gemm, has_flashinfer_b12x_moe
cap = torch.cuda.get_device_capability()
gemm, moe = has_flashinfer_b12x_gemm(), has_flashinfer_b12x_moe()
print('CUDA capability:', cap, '| b12x GEMM:', gemm, '| b12x MoE:', moe)
assert cap[0] == 12 and gemm and moe, 'NVFP4 b12x unavailable; refusing a silent fallback'
'''


def profiles():
    return c.read_json(c.REPO / 'runtime/profiles.json')


def profile(name):
    return profiles()['models'][name]


def env():
    root = c.home()
    return {**os.environ, **profiles()['environment'],
            'HF_HOME': str(root / 'cache/huggingface'),
            'UV_CACHE_DIR': str(root / 'cache/uv'),
            'UV_PYTHON_INSTALL_DIR': str(root / 'runtime/python'),
            'XDG_CACHE_HOME': str(root / 'cache')}


def require_spark():
    if sys.platform != 'linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('The supplied runtime targets Linux ARM64 DGX Spark. Use ./bac dev llm plan MODEL to inspect it on another host.')
    if not shutil.which('nvidia-smi'):
        raise RuntimeError('NVIDIA driver tools are missing; complete the Spark OS/driver setup first.')


def bootstrap_uv():
    existing = shutil.which('uv')
    if existing:
        return existing
    tools = c.home() / 'runtime/tools'
    c.owned_directory(tools)
    if not (tools / 'bin/python').exists():
        c.run([sys.executable, '-m', 'venv', tools])
    executable = tools / 'bin/uv'
    if not executable.exists():
        c.run([tools / 'bin/python', '-m', 'pip', 'install', 'uv'], env=env())
    return str(executable)


def runtime():
    root = c.home() / 'runtime'
    venv = c.owned_directory(root / 'vllm-env')
    desired = {k: profiles()[k] for k in ('python', 'packages')}
    installed = c.read_json(root / 'installed.json')
    if installed and installed != desired:
        raise RuntimeError('Runtime pins changed. App updates never replace the runtime. Explicitly remove-runtime and run setup again when ready.')
    if not installed:
        uv = bootstrap_uv()
        if not (venv / 'bin/python').exists():
            c.run([uv, 'venv', venv, '--python', desired['python']], env=env())
        c.run([uv, 'pip', 'install', '--python', venv / 'bin/python', *desired['packages'], '--torch-backend=auto'], env=env())
        c.run([uv, 'pip', 'check', '--python', venv / 'bin/python'], env=env())
        frozen = c.run([uv, 'pip', 'freeze', '--python', venv / 'bin/python'], env=env(), capture_output=True, text=True).stdout
        (root / 'resolved-requirements.txt').write_text(frozen)
        c.write_json(root / 'installed.json', desired)
    if not (venv / 'bin/vllm').exists():
        raise RuntimeError('vLLM executable is missing. Run remove-runtime, then setup again.')
    c.run([venv / 'bin/python', '-c', KERNEL_CHECK], env=env())
    return venv


def setup(name):
    require_spark()
    venv = runtime()
    folder = c.owned_directory(c.home() / 'models' / name)
    wanted = {**profile(name), 'environment': profiles()['environment']}
    installed = c.read_json(folder / 'installed.json')
    if installed == wanted and (folder / 'weights/config.json').exists():
        print(name + ': already installed; model download skipped.')
        return
    selected = c.read_json(c.home() / 'llm.json', {})
    if selected.get('profile') == name and c.active('bac-llm'):
        raise RuntimeError('Stop the selected model before replacing its installation.')
    if installed and installed != wanted:
        raise RuntimeError('Model profile changed. Remove this model explicitly, then run setup again.')
    folder.mkdir(parents=True, exist_ok=True)
    c.run([venv / 'bin/hf', 'download', wanted['id'], '--revision', wanted['revision'], '--local-dir', folder / 'weights'], env=env())
    if 'template_url' in wanted:
        with urllib.request.urlopen(wanted['template_url'], timeout=60) as response:
            template = response.read()
        if hashlib.sha256(template).hexdigest() != wanted['template_sha256']:
            raise RuntimeError('Gemma chat template checksum mismatch; model was not marked ready.')
        (folder / 'tool_chat_template_gemma4.jinja').write_bytes(template)
    c.write_json(folder / 'installed.json', wanted)
    print(name + ' is installed. Start it with: ./bac dev llm start ' + name)


def command(name, installed=False):
    root = c.home()
    folder = c.owned_directory(root / 'models' / name) if installed else root / 'models' / name
    spec = c.read_json(folder / 'installed.json') if installed else profile(name)
    if not spec or (installed and not (folder / 'weights/config.json').exists()):
        raise RuntimeError('Model not installed. Run ./bac dev llm setup ' + name)
    args = [root / 'runtime/vllm-env/bin/vllm', 'serve', folder / 'weights', *spec['args'],
            '--host', '127.0.0.1', '--port', '8000', '--served-model-name', 'bac-local']
    if 'template_url' in spec:
        args.extend(['--chat-template', folder / 'tool_chat_template_gemma4.jinja'])
    return [str(x) for x in args], spec


def start(name):
    require_spark()
    c.require_systemd()
    args, spec = command(name, installed=True)
    if not (c.home() / 'runtime/vllm-env/bin/vllm').exists():
        raise RuntimeError('Runtime missing. Run ./bac dev llm setup ' + name)
    current = c.read_json(c.home() / 'llm.json', {})
    if c.active('bac-llm'):
        if not c.is_owned_unit('bac-llm'):
            raise RuntimeError('Existing bac-llm service is not managed by this tool.')
        if current.get('profile') == name:
            print(name + ' is already starting/running. Use ./bac dev llm check for readiness.')
            return
        c.require_idle()
        c.service('bac-llm', 'stop')
    if not c.port_free(8000):
        raise RuntimeError('Port 8000 is already used. No unrelated process was stopped.')
    environment = {**spec['environment'], 'HF_HOME': str(c.home() / 'cache/huggingface'),
                   'XDG_CACHE_HOME': str(c.home() / 'cache')}
    c.install_unit('bac-llm', args, environment)
    c.write_json(c.home() / 'llm.json', {'profile': name, 'model_id': spec['id'],
                 'revision': spec['revision'], 'base_url': 'http://127.0.0.1:8000/v1', 'served_model': 'bac-local'})
    c.service('bac-llm', 'enable')
    c.service('bac-llm', 'start')
    print(name + ' is starting on http://127.0.0.1:8000/v1 (all agents: bac-local).')
    print('First startup compiles kernels. Check: ./bac dev llm check | Logs: ./bac dev llm logs')


def check(wait=0):
    def probe():
        data = c.get_json('http://127.0.0.1:8000/v1/models', timeout=5)
        rows = data.get('data') if isinstance(data,dict) else None
        if not isinstance(rows,list) or 'bac-local' not in [m.get('id') for m in rows if isinstance(m,dict)]:
            raise RuntimeError('The endpoint does not expose bac-local.')
    c.wait_ready(probe, 'Model endpoint http://127.0.0.1:8000/v1 (bac-local)', wait, 'bac-llm')


def remove(name, yes=False):
    target = c.owned_directory(c.home() / 'models' / name)
    print('Model files to remove:', target)
    print('The other model, vLLM environment and global Hugging Face cache are preserved.')
    if not yes:
        print('Preview only. Add --yes to remove these files.')
        return
    current = c.read_json(c.home() / 'llm.json', {})
    if current.get('profile') == name:
        c.require_idle()
        if c.is_owned_unit('bac-llm'):
            c.service('bac-llm', 'stop')
            c.service('bac-llm', 'disable')
        (c.home() / 'llm.json').unlink(missing_ok=True)
    c.remove_directory(target)
    print(name + ': model files removed.')


def remove_runtime(yes=False):
    target = c.owned_directory(c.home() / 'runtime/vllm-env')
    print('Runtime environment to remove:', target)
    print('Downloaded models and recorded dependency versions are preserved.')
    if not yes:
        print('Preview only. Add --yes to remove the environment.')
        return
    c.require_idle()
    if c.is_owned_unit('bac-llm'):
        c.service('bac-llm', 'stop')
        c.service('bac-llm', 'disable')
    c.remove_directory(target)
    (c.home() / 'runtime/installed.json').unlink(missing_ok=True)
    (c.home() / 'llm.json').unlink(missing_ok=True)
