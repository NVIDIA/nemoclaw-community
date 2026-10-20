#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Public Hermes dashboard port: rewrite Host to the in-sandbox bind.

Hermes dashboard uvicorn rejects Host: dgx-ip:18789 with 400. Inner OpenShell
forwards stay on 127.0.0.1. This proxy binds the public port and sets
Host: 127.0.0.1:18789 on the backend hop. No tokens on argv or in URLs.
"""

from __future__ import annotations

import os
import socket
import sys
import threading


def publish_bind() -> str:
    raw = (os.environ.get("E2E_PUBLISH_BIND") or "127.0.0.1").strip()
    if raw in {"127.0.0.1", "0.0.0.0"}:
        return raw
    parts = raw.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return raw
    return "127.0.0.1"


def rewrite_host_header(head: bytes, host: bytes) -> bytes:
    lines = head.split(b"\r\n")
    if not lines:
        return head
    out = [lines[0]]
    replaced = False
    for line in lines[1:]:
        if line.lower().startswith(b"host:"):
            out.append(b"Host: " + host)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(1, b"Host: " + host)
    return b"\r\n".join(out)


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        return
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass  # Peer already closed this half of the tunnel.


def _handle(
    client: socket.socket,
    backend_host: str,
    backend_port: int,
    rewrite_host: bytes,
) -> None:
    backend = None
    try:
        peeked = client.recv(65536)
        if not peeked:
            return
        backend = socket.create_connection((backend_host, backend_port), timeout=10)
        backend.settimeout(None)
        client.settimeout(None)
        if b"\r\n\r\n" in peeked:
            head, extra = peeked.split(b"\r\n\r\n", 1)
            backend.sendall(rewrite_host_header(head, rewrite_host) + b"\r\n\r\n" + extra)
        else:
            backend.sendall(peeked)
        up = threading.Thread(target=_pump, args=(backend, client), daemon=True)
        up.start()
        _pump(client, backend)
        up.join()
    except OSError:
        return
    finally:
        if backend is not None:
            try:
                backend.close()
            except OSError:
                pass  # Backend already closed this socket.
        try:
            client.close()
        except OSError:
            pass  # Browser already closed this socket.


def main() -> int:
    if len(sys.argv) < 4:
        print(
            "usage: e2e-hermes-ui-host-proxy.py <listen-port> <backend-host> "
            "<backend-port> [rewrite-host]",
            file=sys.stderr,
        )
        return 2
    listen_port = int(sys.argv[1])
    backend_host = sys.argv[2]
    backend_port = int(sys.argv[3])
    rewrite_host = (sys.argv[4] if len(sys.argv) > 4 else "127.0.0.1:18789").encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((publish_bind(), listen_port))
    sock.listen(64)
    while True:
        client, _addr = sock.accept()
        threading.Thread(
            target=_handle,
            args=(client, backend_host, backend_port, rewrite_host),
            daemon=True,
        ).start()


if __name__ == "__main__":
    raise SystemExit(main())
