# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Disposable validation only: real PVC telemetry + namespace-local SMTP catcher.

Print a manifest: python3 storage_validation_fixture.py manifest CLASS [synthetic]
The namespace is deliberately fixed; never point the filler at an existing disk.
Synthetic mode never writes volume data and is not proof of live expansion.
"""
import json
import os
from pathlib import Path
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

NAMESPACE = 'sre-storage-validation-20261005'
MESSAGES = []


def sample():
    if os.environ.get('SYNTHETIC') == 'true':
        return {'capacity': 1073741824, 'used': 944892805, 'synthetic': True}
    fs = os.statvfs('/data')
    return {'capacity': fs.f_blocks * fs.f_frsize,
            'used': (fs.f_blocks - fs.f_bfree) * fs.f_frsize, 'synthetic': False}


class HTTP(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/messages':
            result = {'messages': MESSAGES}
        elif url.path == '/state':
            result = sample()
        elif url.path == '/fill':
            state = sample()
            if state['synthetic'] or not 500000000 <= state['capacity'] <= 2147483648:
                self.send_error(409, 'refusing to fill synthetic or non-disposable-size filesystem')
                return
            needed = max(0, int(state['capacity'] * .88) - state['used'])
            if needed > 1073741824:
                self.send_error(409, 'fill exceeds 1Gi safety limit')
                return
            with open('/data/validation-fill', 'ab') as handle:
                chunk = b'x' * 1048576
                while needed:
                    count = min(needed, len(chunk))
                    handle.write(chunk[:count])
                    needed -= count
                handle.flush()
                os.fsync(handle.fileno())
            result = sample()
        elif url.path == '/api/v1/query':
            expression = parse_qs(url.query).get('query', [''])[0]
            state = sample()
            value = time.time() if expression.startswith('timestamp(') else state['used'] if 'used_bytes' in expression else state['capacity']
            result = {'status': 'success', 'data': {'resultType': 'vector', 'result': [
                {'metric': {'namespace': NAMESPACE, 'persistentvolumeclaim': 'validation-data',
                            'cluster': 'storage-validation', 'instance': 'isolated-fixture'},
                 'value': [time.time(), str(value)]}]}}
        else:
            self.send_error(404)
            return
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 isolated validation SMTP\r\n')
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return
            verb = line.split(b' ', 1)[0].strip().upper()
            if verb in (b'EHLO', b'HELO'):
                self.wfile.write(b'250 validation\r\n')
            elif verb == b'DATA':
                self.wfile.write(b'354 end with dot\r\n')
                parts = []
                size = 0
                while True:
                    part = self.rfile.readline(65536)
                    if not part or part == b'.\r\n':
                        break
                    size += len(part)
                    if size > 1048576:
                        return
                    parts.append(part)
                MESSAGES.append(b''.join(parts).decode('utf-8', errors='replace'))
                del MESSAGES[:-50]
                self.wfile.write(b'250 captured\r\n')
            elif verb == b'QUIT':
                self.wfile.write(b'221 bye\r\n')
                return
            else:
                self.wfile.write(b'250 OK\r\n')


def manifest(storage_class, synthetic=False):
    def obj(kind, name, **fields):
        return {'apiVersion': 'apps/v1' if kind == 'Deployment' else 'v1', 'kind': kind,
                'metadata': {'name': name, 'namespace': NAMESPACE}, **fields}
    security = {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                'capabilities': {'drop': ['ALL']}, 'runAsNonRoot': True,
                'seccompProfile': {'type': 'RuntimeDefault'}}
    pod_security = {'runAsNonRoot': True, 'seccompProfile': {'type': 'RuntimeDefault'}}
    if storage_class == 'local-path':
        pod_security.update(runAsUser=1001, fsGroup=1001)
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NAMESPACE,
         'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}},
        obj('ConfigMap', 'storage-validation-script', data={'fixture.py': Path(__file__).read_text()}),
        obj('PersistentVolumeClaim', 'validation-data', spec={'accessModes': ['ReadWriteOnce'],
            'storageClassName': storage_class, 'resources': {'requests': {'storage': '1Gi'}}}),
        obj('Service', 'storage-validation', spec={'selector': {'app': 'storage-validation'},
            'ports': [{'name': 'http', 'port': 8080}, {'name': 'smtp', 'port': 2525}]}),
        obj('Deployment', 'storage-validation', spec={'replicas': 1,
            'strategy': {'type': 'Recreate'},
            'selector': {'matchLabels': {'app': 'storage-validation'}},
            'template': {'metadata': {'labels': {'app': 'storage-validation'}}, 'spec': {
                'automountServiceAccountToken': False,
                'securityContext': pod_security,
                'containers': [{'name': 'fixture', 'image': 'docker.io/library/python:3.12-slim',
                    'command': ['python3', '/fixture/fixture.py', 'serve'],
                    'env': [{'name': 'SYNTHETIC', 'value': str(synthetic).lower()}],
                    'securityContext': security,
                    'resources': {'requests': {'cpu': '20m', 'memory': '64Mi'},
                                  'limits': {'cpu': '500m', 'memory': '128Mi'}},
                    'readinessProbe': {'httpGet': {'path': '/state', 'port': 8080}},
                    'volumeMounts': [{'name': 'script', 'mountPath': '/fixture', 'readOnly': True},
                                     {'name': 'data', 'mountPath': '/data'}]}],
                'volumes': [{'name': 'script', 'configMap': {'name': 'storage-validation-script'}},
                            {'name': 'data', 'persistentVolumeClaim': {'claimName': 'validation-data'}}]}}})]}


if __name__ == '__main__':
    if sys.argv[1] == 'manifest':
        print(json.dumps(manifest(sys.argv[2], 'synthetic' in sys.argv[3:])))
    else:
        smtp = socketserver.ThreadingTCPServer(('0.0.0.0', 2525), SMTP)
        threading.Thread(target=smtp.serve_forever, daemon=True).start()
        ThreadingHTTPServer(('0.0.0.0', 8080), HTTP).serve_forever()
