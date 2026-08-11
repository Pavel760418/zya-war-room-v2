#!/usr/bin/env python3
"""IP-allowlist TCP proxy for War Room Streamlit (no root required).

Listens on WARROOM_PROXY_PORT (default 8501) and forwards only from
WARROOM_ALLOWED_IPS to 127.0.0.1:WARROOM_BACKEND_PORT (default 8502).
"""
from __future__ import annotations

import os
import socket
import threading


def _allowed() -> set[str]:
    raw = os.environ.get("WARROOM_ALLOWED_IPS", "127.0.0.1")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RD)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(client: socket.socket, addr: tuple[str, int], backend_addr: tuple[str, int], allowed: set[str]) -> None:
    ip = addr[0]
    if ip not in allowed:
        client.close()
        return
    try:
        backend = socket.create_connection(backend_addr, timeout=10)
    except OSError:
        client.close()
        return
    t1 = threading.Thread(target=_pipe, args=(client, backend), daemon=True)
    t2 = threading.Thread(target=_pipe, args=(backend, client), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    try:
        client.close()
    except OSError:
        pass
    try:
        backend.close()
    except OSError:
        pass


def main() -> None:
    listen_host = os.environ.get("WARROOM_PROXY_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("WARROOM_PROXY_PORT", "8501"))
    backend_host = os.environ.get("WARROOM_BACKEND_HOST", "127.0.0.1")
    backend_port = int(os.environ.get("WARROOM_BACKEND_PORT", "8502"))
    allowed = _allowed()
    backend_addr = (backend_host, backend_port)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(128)
    print(
        f"warroom-proxy listen={listen_host}:{listen_port} "
        f"backend={backend_host}:{backend_port} allow={sorted(allowed)}",
        flush=True,
    )
    while True:
        client, addr = srv.accept()
        threading.Thread(
            target=_handle,
            args=(client, addr, backend_addr, allowed),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
