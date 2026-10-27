# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Chat with a CAD agent folder in the browser: the agent's steps as they happen (chat.py), and
a 3D view of the mesh and the model. Single user; closing the tab stops the task.

    CAD_AGENT_TIMEOUT=900 python web.py AGENT_DIR [MESH]      (chat.sh starts it; see README.md)
"""
import json
import os
import select
import shutil
import socket
import sys
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from chat import APP, MODEL, Task, check_model, ingest, to_obj

PAGE = Path(__file__).with_name('web.html')
VIEW = Path('/tmp/model.obj')  # model.FCStd tessellated for the viewer
SNAPSHOT = Path('/tmp/model.FCStd')  # the settled copy VIEW and the download are made from
LISTEN = 8765  # in the container; chat.sh publishes it on CAD_WEB_PORT
PORT = os.environ.get('CAD_WEB_PORT', str(LISTEN))  # the port the browser uses
NAMES = ('localhost', '127.0.0.1', '[::1]')
TYPES = {'/upload': 'application/octet-stream', '/chat': 'application/json'}
MAX_UPLOAD = 200 << 20
MAX_IMAGE = 4 << 20  # an agent's render shown in the chat; larger ones are left out
HISTORY = []  # the conversation, from tasks that completed
BUSY, VIEW_LOCK = threading.Lock(), threading.Lock()
VIEWED = {'stamp': None, 'copied': False, 'error': ''}  # the save SNAPSHOT and VIEW come from


def local(netloc: str) -> bool:
    """This machine, as the browser names it (it leaves out port 80)."""
    return netloc in {f'{n}:{PORT}' for n in NAMES} or (PORT == '80' and netloc in NAMES)


def stamp(path: Path):
    """A file's version: its time (ns) and size; None when absent."""
    with suppress(FileNotFoundError):
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    return None


def snapshot() -> dict:
    """Once per save of model.FCStd, while the agent may be writing it: a settled copy (same
    version before and after reading; replaced whole, so a download in progress keeps its
    file), then tessellated for the viewer. Returns VIEWED: copied, and the viewer's error."""
    with VIEW_LOCK:
        current = stamp(MODEL)
        if current != VIEWED['stamp']:
            copied, error = False, 'model.FCStd keeps changing'
            with suppress(FileNotFoundError):  # set aside or deleted meanwhile
                for _ in range(20):
                    before, data = stamp(MODEL), MODEL.read_bytes()
                    if before == stamp(MODEL) and before and before[1] == len(data):
                        tmp = SNAPSHOT.with_suffix('.part')
                        tmp.write_bytes(data)
                        tmp.replace(SNAPSHOT)
                        copied = True
                        try:
                            to_obj(SNAPSHOT, VIEW)
                            error = ''
                        except Exception as e:  # noqa: BLE001  (shown in the page)
                            error = str(e)
                        break
                    time.sleep(0.25)
            VIEWED.update(stamp=current, copied=copied, error=error)
        return VIEWED


class Handler(BaseHTTPRequestHandler):
    timeout = 60  # a request body that stops coming

    def reply(self, code: int, body: bytes = b'', kind: str = 'text/plain') -> None:
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, kind: str = 'text/plain', download: str = '') -> None:
        """A file only ever replaced whole (renamed or rewritten here); 304 when the page has
        this version (ETag from its time in ns and size)."""
        with path.open('rb') as f:
            stat = os.fstat(f.fileno())
            tag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            if self.headers.get('If-None-Match') == tag:
                self.send_response(304)
                return self.end_headers()
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(stat.st_size))
            self.send_header('ETag', tag)
            self.send_header('Cache-Control', 'no-cache')
            if download:
                self.send_header('Content-Disposition', f'attachment; filename="{download}"')
            self.end_headers()
            shutil.copyfileobj(f, self.wfile)

    def trusted(self) -> bool:
        """Only the page from this machine: the Host it uses (no DNS rebinding), and its Origin
        when the browser sends one (another site's page sends its own)."""
        origin = self.headers.get('Origin')
        return local(self.headers.get('Host', '')) and (origin is None or local(urlparse(origin).netloc))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self.trusted():
            self.reply(403, b'forbidden')
        elif path == '/':
            self.send_file(PAGE, 'text/html; charset=utf-8')
        elif path == '/reference.obj' and (APP / 'reference.obj').exists():
            self.send_file(APP / 'reference.obj')
        elif path in ('/model.obj', '/model.FCStd') and MODEL.exists():
            done = snapshot()
            if not done['copied']:
                self.reply(404 if not MODEL.exists() else 503, done['error'].encode())
            elif path == '/model.FCStd':  # the saved model, even when the viewer cannot show it
                self.send_file(SNAPSHOT, 'application/octet-stream', 'model.FCStd')
            elif done['error']:
                self.reply(500, done['error'].encode())
            else:
                self.send_file(VIEW)
        else:
            self.reply(404, b'not found')

    def read_body(self, left: int, out=None) -> int:
        """Read the request body into out (or discard it); returns the bytes that never came."""
        while left > 0 and (chunk := self.rfile.read(min(left, 1 << 20))):
            if out:
                out.write(chunk)
            left -= len(chunk)
        return left

    def refusal(self, path: str, length: int):
        """Why a POST is refused from its headers, as (code, reason), or None."""
        if path not in TYPES:
            return 404, b'not found'
        # A JSON or binary POST from another site needs a CORS preflight, never answered here.
        if not self.trusted() or self.headers.get('Content-Type') != TYPES[path]:
            return 403, b'forbidden'
        if length <= 0:
            return 400, b'bad request'
        if length > MAX_UPLOAD:
            return 413, b'too large'
        return None

    def refuse(self, code: int, reason: bytes, unread: int = 0) -> None:
        """Answer and close; the unread body (up to MAX_UPLOAD) is read first, so the page
        gets the reason rather than a reset connection."""
        self.close_connection = True
        with suppress(OSError):
            self.read_body(min(unread, MAX_UPLOAD))
            self.reply(code, reason)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        try:
            length = int(self.headers['Content-Length'])
        except (TypeError, ValueError):
            length = 0
        refused = self.refusal(url.path, length)
        if refused:
            return self.refuse(*refused, length)
        if not BUSY.acquire(blocking=False):
            return self.refuse(409, b'the agent is working; wait for it to finish', length)
        try:
            self.upload(url, length) if url.path == '/upload' else self.chat(length)
        finally:
            BUSY.release()

    def upload(self, url, length: int) -> None:
        """The request body is a mesh (OBJ or STL): a new job, as a mesh given to chat.sh."""
        suffix = Path(parse_qs(url.query).get('name', [''])[0]).suffix.lower()
        if suffix not in ('.obj', '.stl'):
            return self.refuse(400, b'not a mesh: upload an .obj or .stl file', length)
        mesh = Path(f'/tmp/upload{suffix}')
        try:
            with mesh.open('wb') as f:
                left = self.read_body(length, f)
            if left:
                return self.refuse(400, b'upload cut short')
            ingest(mesh)
        except OSError:  # the connection failed or timed out mid-body
            self.close_connection = True
            return
        except Exception as e:  # noqa: BLE001  (the page shows it)
            return self.refuse(400, str(e).encode())
        finally:
            mesh.unlink(missing_ok=True)
        HISTORY.clear()
        self.reply(200, b'ok')

    def connected(self) -> bool:
        """False once the page has closed the connection (it sends nothing more otherwise)."""
        return not (select.select([self.connection], [], [], 0)[0]
                    and not self.connection.recv(1, socket.MSG_PEEK))

    def chat(self, length: int) -> None:
        """The task's steps as server-sent events: call, result, text, note, and model when
        model.FCStd is saved, image (a data URL) when the agent looks at an image. The stream
        ends with the task; a closed page stops it."""
        try:
            prompt = json.loads(self.rfile.read(length))['message'].strip()
        except (KeyError, TypeError, ValueError, AttributeError):
            prompt = ''
        if not prompt:
            return self.refuse(400, b'bad request: send {"message": "..."}')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        task, saved = Task(self.server.agent, HISTORY, prompt), stamp(MODEL)
        try:
            for kind, text in task.steps(self.connected):
                if kind != 'image' or len(text) <= MAX_IMAGE * 4 // 3:  # base64 of MAX_IMAGE bytes
                    self.wfile.write(f'event: {kind}\ndata: {json.dumps(text)}\n\n'.encode())
                if (now := stamp(MODEL)) != saved:
                    saved = now
                    self.wfile.write(b'event: model\ndata: ""\n\n')
                self.wfile.flush()
        except OSError:
            pass  # the page went away
        finally:
            task.stop()
        if task.history is not None:
            HISTORY[:] = task.history

    def log_message(self, *args) -> None:
        pass


def main(agent_dir: str = '/agent', mesh: str = '') -> None:
    check_model(Path(agent_dir))
    if mesh:
        ingest(Path(mesh))
    server = ThreadingHTTPServer(('0.0.0.0', LISTEN), Handler)
    server.agent = Path(agent_dir)
    with suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == '__main__':
    main(*sys.argv[1:3])
