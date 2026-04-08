"""Projector helper daemon — owns the RS232 serial port.

Listens on a Unix socket for JSON-line commands from the LUCID component
(running as normal user). Handles serial open/close and command dispatch.

Start: lucid-projector-helper
Socket: LUCID_PROJECTOR_SOCKET or /run/lucid/projector.sock
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
from pathlib import Path
from typing import Any, Optional

from .protocol import CMD_PING, CMD_RESET, CMD_SEND, CMD_STATUS, DEFAULT_SOCKET_PATH
from .serial_conn import ProjectorSerial, find_usb_serial_device

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("lucid.projector.helper")

LUCID_GROUP = "lucid"
SOCKET_MODE = 0o660


def _get_socket_path() -> str:
    return os.environ.get("LUCID_PROJECTOR_SOCKET", DEFAULT_SOCKET_PATH)


def _gid_for(name: str) -> Optional[int]:
    try:
        import grp
        return grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return None


class HelperState:
    """Manages serial port lifecycle and command dispatch."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._serial: Optional[ProjectorSerial] = None
        self._port: str = ""
        self._baudrate: int = 9600
        self._timeout: float = 1.0

    def init(self, port: str = "", baudrate: int = 9600, timeout: float = 1.0) -> dict:
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            resolved_port = port or find_usb_serial_device()
            if not resolved_port:
                return {"ok": False, "error": "No serial port found"}
            try:
                self._serial = ProjectorSerial(resolved_port, baudrate, timeout)
                self._serial.open()
                self._port = resolved_port
                self._baudrate = baudrate
                self._timeout = timeout
                logger.info("Serial opened: %s @ %d baud", resolved_port, baudrate)
                return {"ok": True, "port": resolved_port}
            except Exception as exc:
                self._serial = None
                return {"ok": False, "error": str(exc)}

    def send(self, command: str, value: Optional[int] = None) -> dict:
        with self._lock:
            if not self._serial or not self._serial.is_open:
                return {"ok": False, "error": "Serial port not open"}
            try:
                self._serial.send(command, value)
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    def status(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "connected": self._serial is not None and self._serial.is_open,
                "port": self._port,
                "baudrate": self._baudrate,
            }

    def reset(self) -> dict:
        with self._lock:
            if self._serial:
                self._serial.close()
                self._serial = None
            if not self._port:
                return {"ok": False, "error": "No port configured"}
            try:
                self._serial = ProjectorSerial(self._port, self._baudrate, self._timeout)
                self._serial.open()
                return {"ok": True, "port": self._port}
            except Exception as exc:
                self._serial = None
                return {"ok": False, "error": str(exc)}

    def shutdown(self) -> None:
        with self._lock:
            if self._serial:
                self._serial.close()
                self._serial = None


def _handle_request(state: HelperState, req: dict[str, Any]) -> dict[str, Any]:
    rid = req.get("id", 0)
    cmd = req.get("cmd", "")

    if cmd == CMD_PING:
        result = {"ok": True}
    elif cmd == CMD_STATUS:
        result = state.status()
    elif cmd == CMD_SEND:
        result = state.send(req.get("command", ""), req.get("value"))
    elif cmd == CMD_RESET:
        result = state.reset()
    else:
        result = {"ok": False, "error": f"unknown command: {cmd}"}

    result["id"] = rid
    return result


def _handle_client(conn: socket.socket, state: HelperState) -> None:
    try:
        conn.settimeout(10.0)
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        line = data.split(b"\n", 1)[0]
        req = json.loads(line.decode("utf-8"))
        resp = _handle_request(state, req)
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    except Exception:
        logger.exception("Client handler error")
    finally:
        conn.close()


def _setup_socket(path: str) -> socket.socket:
    sock_path = Path(path)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    sock.listen(5)
    os.chmod(str(sock_path), SOCKET_MODE)

    gid = _gid_for(LUCID_GROUP)
    if gid is not None:
        try:
            os.chown(str(sock_path), -1, gid)
            os.chown(str(sock_path.parent), -1, gid)
            os.chmod(str(sock_path.parent), 0o775)
        except PermissionError:
            logger.warning("Could not set socket group to '%s'", LUCID_GROUP)

    return sock


def main() -> None:
    socket_path = _get_socket_path()
    logger.info("Projector helper starting (socket: %s, user: %s)",
                socket_path, os.getenv("USER", "?"))

    state = HelperState()

    # Auto-detect and open serial port
    port = os.environ.get("LUCID_PROJECTOR_PORT", "") or find_usb_serial_device()
    baudrate = int(os.environ.get("LUCID_PROJECTOR_BAUDRATE", "9600"))
    if port:
        result = state.init(port, baudrate)
        if result["ok"]:
            logger.info("Serial port ready: %s", port)
        else:
            logger.warning("Serial port init failed: %s", result.get("error"))
    else:
        logger.warning("No USB serial device found, will wait for commands")

    sock = _setup_socket(socket_path)
    logger.info("Listening on %s", socket_path)

    stop = threading.Event()

    def _signal_handler(signum: int, _: Any) -> None:
        logger.info("Received signal %d, shutting down", signum)
        stop.set()
        state.shutdown()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            conn, _ = sock.accept()
            threading.Thread(
                target=_handle_client, args=(conn, state), daemon=True,
            ).start()
        except socket.timeout:
            continue
        except Exception:
            if not stop.is_set():
                logger.exception("Accept error")

    sock.close()
    Path(socket_path).unlink(missing_ok=True)
    logger.info("Projector helper stopped")


if __name__ == "__main__":
    main()
