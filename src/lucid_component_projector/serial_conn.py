"""RS232 serial connection to Optoma projector.

Wraps pyserial with auto-detection of USB serial devices and
the Optoma ASCII command protocol.
"""
from __future__ import annotations

import glob
import logging
import threading
from typing import Optional

import serial

logger = logging.getLogger("lucid.component.projector.serial")

# Optoma RS232 ASCII commands — static (no parameters)
STATIC_COMMANDS: dict[str, str] = {
    "on":       "~0000 1\r",
    "off":      "~0000 0\r",
    "hdmi1":    "~00305 1\r",
    "hdmi2":    "~0012 15\r",
    "4:3":      "~0060 1\r",
    "16:9":     "~0060 2\r",
    "up":       "~00140 10\r",
    "down":     "~00140 14\r",
    "left":     "~00140 11\r",
    "right":    "~00140 13\r",
    "enter":    "~00140 12\r",
    "menu":     "~00140 20\r",
    "back":     "~00140 74\r",
}

# Optoma RS232 ASCII commands — dynamic (require integer value)
DYNAMIC_COMMANDS: dict[str, tuple[str, int, int]] = {
    # command_key: (template_with_n, min_val, max_val)
    "h-image-shift": ("~0063 n\r", -100, 100),
    "v-image-shift": ("~0064 n\r", -100, 100),
    "h-keystone":    ("~0065 n\r",  -40,  40),
    "v-keystone":    ("~0066 n\r",  -40,  40),
}

ALL_COMMANDS = list(STATIC_COMMANDS.keys()) + list(DYNAMIC_COMMANDS.keys())


def find_usb_serial_device() -> Optional[str]:
    """Return first available /dev/ttyUSB* device, or None."""
    devices = sorted(glob.glob("/dev/ttyUSB*"))
    return devices[0] if devices else None


class ProjectorSerial:
    """Thread-safe RS232 connection to an Optoma projector."""

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._lock = threading.Lock()
        self._ser: Optional[serial.Serial] = None

    @property
    def port(self) -> str:
        return self._port

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(self) -> None:
        with self._lock:
            if self._ser and self._ser.is_open:
                return
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self._timeout,
            )
            logger.info("Opened serial port %s @ %d baud", self._port, self._baudrate)

    def close(self) -> None:
        with self._lock:
            if self._ser and self._ser.is_open:
                self._ser.close()
                logger.info("Closed serial port %s", self._port)
            self._ser = None

    def send_static(self, command: str) -> None:
        """Send a static command (no parameters). Raises KeyError if unknown."""
        key = command.lower()
        if key not in STATIC_COMMANDS:
            raise KeyError(f"Unknown static command: {command}")
        self._write(STATIC_COMMANDS[key])

    def send_dynamic(self, command: str, value: int) -> None:
        """Send a dynamic command with an integer value. Validates range."""
        key = command.lower()
        if key not in DYNAMIC_COMMANDS:
            raise KeyError(f"Unknown dynamic command: {command}")
        template, min_val, max_val = DYNAMIC_COMMANDS[key]
        if not (min_val <= value <= max_val):
            raise ValueError(
                f"{command} value {value} out of range [{min_val}, {max_val}]"
            )
        ascii_cmd = template.replace("n", str(value))
        self._write(ascii_cmd)

    def send(self, command: str, value: Optional[int] = None) -> None:
        """Send a command — dispatches to static or dynamic based on command key."""
        key = command.lower()
        if key in STATIC_COMMANDS:
            self.send_static(key)
        elif key in DYNAMIC_COMMANDS:
            if value is None:
                raise ValueError(f"{command} requires a 'value' parameter")
            self.send_dynamic(key, value)
        else:
            raise KeyError(f"Unknown command: {command}")

    def _write(self, data: str) -> None:
        with self._lock:
            if not self._ser or not self._ser.is_open:
                raise ConnectionError("Serial port not open")
            self._ser.write(data.encode("utf-8"))
            logger.debug("Sent: %r", data)
