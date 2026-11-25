# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The relay into the ingress (decision 0024): a listener on the host's 127.0.0.1 whose
every connection is carried into the ingress container through the Docker API.

The engine forwards nothing but its Docker socket (decision 0004), and the ingress listens
on its own loopback only. Each connection runs a small copier in the ingress, joined to a
Docker exec stream: bytes sent go to the copier's standard input unchanged; what comes back
is Docker's framed output, unpacked here. About 40 ms per connection on an Apple Silicon Mac.
"""

from __future__ import annotations

import contextlib
import socket
import struct
import threading
from collections.abc import Callable
from typing import Any

from mirrordimensions.network.sandbox import INGRESS_NAME, INGRESS_PORT

# Runs inside the ingress: joins standard input and output to the ingress's own listener.
COPIER = (
    "import os,socket,threading\n"
    f"s=socket.create_connection(('127.0.0.1',{INGRESS_PORT}))\n"
    "def up():\n"
    "    while True:\n"
    "        b=os.read(0,65536)\n"
    "        if not b:\n"
    "            s.shutdown(socket.SHUT_WR)\n"
    "            break\n"
    "        s.sendall(b)\n"
    "threading.Thread(target=up,daemon=True).start()\n"
    "while True:\n"
    "    b=s.recv(65536)\n"
    "    if not b:\n"
    "        break\n"
    "    os.write(1,b)\n"
)
STDOUT = 1


def unframe(buffer: bytearray) -> list[bytes]:
    """Take every complete standard-output frame off the front of `buffer`."""
    out: list[bytes] = []
    while len(buffer) >= 8:
        kind, size = struct.unpack(">BxxxL", bytes(buffer[:8]))
        if len(buffer) < 8 + size:
            break
        if kind == STDOUT:
            out.append(bytes(buffer[8 : 8 + size]))
        del buffer[: 8 + size]
    return out


def _carry(client: socket.socket, open_stream: Callable[[], Any]) -> None:
    stream = open_stream()

    def up() -> None:
        try:
            while chunk := client.recv(65536):
                stream.sendall(chunk)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                stream.shutdown(socket.SHUT_WR)

    threading.Thread(target=up, daemon=True).start()
    buffer = bytearray()
    try:
        while chunk := stream.recv(65536):
            buffer.extend(chunk)
            for payload in unframe(buffer):
                client.sendall(payload)
    except OSError:
        pass
    finally:
        for end in (client, stream):
            with contextlib.suppress(OSError):
                end.close()


def serve(docker: Any, port: int, ready: Callable[[], None] | None = None) -> None:
    """Relay connections on 127.0.0.1:port into the ingress until interrupted."""
    listener = socket.create_server(("127.0.0.1", port))
    if ready is not None:
        ready()
    with listener:
        while True:
            client, _ = listener.accept()
            threading.Thread(
                target=_carry,
                args=(client, lambda: docker.exec_socket(INGRESS_NAME, ["python3", "-c", COPIER])),
                daemon=True,
            ).start()
