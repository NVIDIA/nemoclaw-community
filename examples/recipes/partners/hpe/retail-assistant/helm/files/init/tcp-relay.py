# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import socket, threading
def relay(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data: break
            dst.sendall(data)
    except: pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('10.200.0.1', 8001))
srv.listen(5)
while True:
    client, _ = srv.accept()
    try:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.connect(('172.18.0.1', 8001))
        threading.Thread(target=relay, args=(client, upstream), daemon=True).start()
        threading.Thread(target=relay, args=(upstream, client), daemon=True).start()
    except: client.close()
