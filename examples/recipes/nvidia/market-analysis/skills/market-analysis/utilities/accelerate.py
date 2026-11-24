#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run an analysis script on the GPU when this sandbox can, unchanged, and record which engine ran it.

  python3 utilities/accelerate.py status [--out answers/environment.json]
  python3 utilities/accelerate.py run scripts/q2.py [args...] [--engine auto|cpu|gpu]

Write analysis scripts in plain pandas, scikit-learn and NetworkX. `run` uses the interpreter of the matching virtual
environment that scripts/install.sh built: /sandbox/cuda-x-venv on a GPU sandbox (override with CUDA_X_VENV) or
/sandbox/analysis-venv (override with ANALYSIS_VENV). On the GPU it installs the CUDA-X accelerators (cudf.pandas,
cuml.accel, nx-cugraph) before the script imports anything, so the same script runs on cuDF, cuML and nx-cugraph. Set
pass --engine cpu to stay on the CPU (the ACCELERATE_GPU=off environment variable is refused, so a CPU run is always an explicit choice). Inside the script, `json.loads(os.environ['ACCELERATE_ENGINE'])`
is the engine receipt to copy into the answer (device, the libraries that ran, and host_gpu_usable: whether this sandbox
could use the GPU). Each run's time is appended to outputs/timings.jsonl in the working directory. `status` probes once
(one CUDA-X operation in a child process), so `gpu_usable` means the stack works. A missing environment is reported as
blocked and nothing is substituted.
"""
import importlib.metadata
import importlib.util
import json
import os
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path

OUT = Path.cwd()
ANALYSIS_VENV = Path(os.environ.get('ANALYSIS_VENV', '/sandbox/analysis-venv'))
CUDA_X_VENV = Path(os.environ.get('CUDA_X_VENV', '/sandbox/cuda-x-venv'))
CUDA_X_LIBS = {'cudf': 'cudf', 'cuml': 'cuml', 'nx_cugraph': 'nx-cugraph'}


def version(name):
    for dist in importlib.metadata.distributions():
        found = (dist.metadata['Name'] or '').lower().replace('_', '-')
        if found == name or found.startswith(name + '-cu'):
            return dist.version
    return None


def host_sees_gpu():
    try:
        listed = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return listed.returncode == 0 and 'GPU' in listed.stdout


def ensure_environment(wants_cpu):
    """Re-run under the virtual environment that matches this machine: CUDA-X on a visible GPU, else the CPU analysis one."""
    use_cuda_x = not wants_cpu and host_sees_gpu() and (CUDA_X_VENV / 'bin' / 'python').exists() and list(CUDA_X_VENV.glob('lib/python*/site-packages/cudf'))
    target = CUDA_X_VENV if use_cuda_x else ANALYSIS_VENV
    python = target / 'bin' / 'python'
    if Path(sys.prefix).resolve() == target.resolve():
        return
    if os.environ.get('MA_ACCELERATE_REEXEC') or not python.exists():
        sys.exit(f'blocked: the analysis environment is missing ({python} not found). Run scripts/install.sh. '
                 'Nothing was substituted. Report the analysis as blocked.')
    os.environ['MA_ACCELERATE_REEXEC'] = '1'
    os.environ['MA_HOST_CUDA_X_VENV'] = '1' if use_cuda_x or (list(CUDA_X_VENV.glob('lib/python*/site-packages/cudf')) and host_sees_gpu()) else '0'
    os.execv(str(python), [str(python), *sys.argv])


def gpu_status(probe=False):
    try:
        listed = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, timeout=30)
        present = listed.returncode == 0 and 'GPU' in listed.stdout
        detail = re.sub(r'\s*\(UUID: [^)]*\)', '', listed.stdout.strip().splitlines()[0]) if present else listed.stderr.strip()[:200]
    except (OSError, subprocess.SubprocessError) as error:
        present, detail = False, f'nvidia-smi unavailable: {error}'
    libraries = {name: version(dist) for name, dist in CUDA_X_LIBS.items() if importlib.util.find_spec(name)}
    usable, error = present and len(libraries) == len(CUDA_X_LIBS), None
    if usable and probe:  # nx-cugraph needs NVRTC loaded first, as install() does
        code = ("from cuda.pathfinder import load_nvidia_dynamic_lib; load_nvidia_dynamic_lib('nvrtc'); "
                "import cudf, cuml, nx_cugraph; assert int(cudf.Series([1, 2, 3]).sum()) == 6")
        done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=300)
        usable = done.returncode == 0
        error = None if usable else ((done.stderr.strip().splitlines() or [''])[-1][:300] or 'probe failed')
    return {'python': sys.version.split()[0], 'gpu_present': present, 'gpu_detail': detail, 'cuda_x': libraries,
            'gpu_usable': usable, 'probe_error': error}


def install():
    """cudf.pandas, cuml.accel and nx-cugraph; must run before pandas, scikit-learn or NetworkX is imported."""
    os.environ.setdefault('NX_CUGRAPH_AUTOCONFIG', 'True')
    from cuda.pathfinder import load_nvidia_dynamic_lib
    load_nvidia_dynamic_lib('nvrtc')
    import cudf.pandas
    cudf.pandas.install()
    import cuml.accel
    cuml.accel.install()


def main():
    args = sys.argv[1:]
    if os.environ.get('ACCELERATE_GPU') == 'off':
        sys.exit('blocked: ACCELERATE_GPU=off is not accepted. To run on the CPU, pass --engine cpu to accelerate.py run '
                 'and say in the answer that this was a CPU run by choice.')
    wants_cpu = (args[:1] == ['run'] and '--engine' in args
                                                               and args[args.index('--engine') + 1:][:1] == ['cpu'])
    ensure_environment(wants_cpu)
    if args[:1] == ['status']:
        text = json.dumps(gpu_status(probe=True), indent=2) + '\n'
        if '--out' in args:
            out = Path(args[args.index('--out') + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
        print(text, end='')
        return
    if args[:1] != ['run'] or len(args) < 2:
        sys.exit(__doc__)
    engine = 'auto'
    if '--engine' in args:
        i = args.index('--engine')
        engine, args = args[i + 1], args[:i] + args[i + 2:]
    gpu_setting = 'auto'
    status = gpu_status()
    # Under --engine cpu the CPU venv has no CUDA-X; report whether the GPU stack exists on this sandbox (probed at status).
    host_usable = status['gpu_usable'] or os.environ.get('MA_HOST_CUDA_X_VENV') == '1'
    device = 'gpu' if engine == 'gpu' or (engine == 'auto' and status['gpu_usable'] and gpu_setting != 'off') else 'cpu'
    if device == 'gpu':
        if not status['gpu_usable']:
            sys.exit('--engine gpu, but this sandbox has no usable GPU stack')
        install()
    receipt = {'device': device, 'host_gpu_usable': host_usable, 'settings_gpu': gpu_setting,
               'libraries': ({'pandas': f"cudf.pandas {status['cuda_x']['cudf']}", 'scikit-learn': f"cuml.accel {status['cuda_x']['cuml']}",
                              'networkx': f"nx-cugraph {status['cuda_x']['nx_cugraph']}"} if device == 'gpu' else
                             {lib: version(lib) for lib in ('pandas', 'scikit-learn', 'networkx')})}
    os.environ['ACCELERATE_ENGINE'] = json.dumps(receipt)
    script = args[1]
    sys.argv = [script, *args[2:]]
    started = time.perf_counter()
    try:
        runpy.run_path(script, run_name='__main__')
    finally:
        record = {'script': script, 'device': device, 'seconds': round(time.perf_counter() - started, 3)}
        (OUT / 'outputs').mkdir(exist_ok=True)
        with open(OUT / 'outputs' / 'timings.jsonl', 'a') as f:
            f.write(json.dumps(record) + '\n')
        print(json.dumps({'engine': receipt, **record}), file=sys.stderr)


if __name__ == '__main__':
    main()
