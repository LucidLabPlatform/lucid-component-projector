"""IPC client for the projector helper daemon.

Used by the LUCID component (running as normal user) to send RS232 commands
to the helper (which owns the serial port). Reconnects on each call.
"""
from __future__ import annotations

import json
import os
import socket
from typing import Any, Optional

from .protocol import CMD_PING, CMD_RESET, CMD_SEND, CMD_STATUS, DEFAULT_SOCKET_PATH


def _socket_path() -> str:
    return os.environ.get("LUCID_PROJECTOR_SOCKET", DEFAULT_SOCKET_PATH)


def _request(cmd: str, **params: Any) -> dict:
    path = _socket_path()
    req = {"id": 1, "cmd": cmd, **params}
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(10.0)
        sock.connect(path)
        sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return {"ok": False, "error": "connection closed"}
            buf += chunk
        line = buf.split(b"\n", 1)[0].decode("utf-8")
        return json.loads(line)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            sock.close()
        except OSError:
            pass


def ping() -> dict:
    """Check if helper is reachable."""
    return _request(CMD_PING)


def send(command: str, value: Optional[int] = None) -> dict:
    """Send an RS232 command to the projector via the helper."""
    params: dict[str, Any] = {"command": command}
    if value is not None:
        params["value"] = value
    return _request(CMD_SEND, **params)


def status() -> dict:
    """Get serial port status from the helper."""
    return _request(CMD_STATUS)


def reset() -> dict:
    """Close and reopen the serial port."""
    return _request(CMD_RESET)
