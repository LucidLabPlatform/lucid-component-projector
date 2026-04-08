"""Projector component — controls Optoma projectors over RS232 serial.

Delegates serial port access to the projector helper daemon (runs as root).
The component communicates with the helper via Unix socket IPC.

Commands:
  power/on, power/off          — power control
  input/hdmi1, input/hdmi2     — input source selection
  aspect/4-3, aspect/16-9      — aspect ratio
  navigate/up, navigate/down, navigate/left, navigate/right,
  navigate/enter, navigate/menu, navigate/back  — OSD navigation
  keystone/set                 — h/v keystone adjustment (requires value)
  image-shift/set              — h/v image shift adjustment (requires value)
  reset, ping, cfg/set         — standard component commands

Telemetry: connected (serial port alive, polled every 10s).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from lucid_component_base import Component, ComponentContext

from . import client as helper_client


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectorComponent(Component):
    """Optoma projector controller via helper daemon."""

    _MONITOR_INTERVAL_S = 10.0

    _DEFAULTS: dict[str, Any] = {
        "serial_port": "",       # auto-detect if empty
        "baudrate": 9600,
    }

    def __init__(self, context: ComponentContext) -> None:
        super().__init__(context)
        self._log = context.logger()
        self._cfg: dict[str, Any] = dict(self._DEFAULTS)
        if context.config:
            for k, v in context.config.items():
                if k in self._cfg:
                    self._cfg[k] = v
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_status: dict[str, Any] = {}

    # ── identity ──────────────────────────────────────────────

    @property
    def component_id(self) -> str:
        return "projector"

    def capabilities(self) -> list[str]:
        return [
            "reset", "ping",
            "power/on", "power/off",
            "input/hdmi1", "input/hdmi2",
            "aspect/4-3", "aspect/16-9",
            "navigate/up", "navigate/down", "navigate/left", "navigate/right",
            "navigate/enter", "navigate/menu", "navigate/back",
            "keystone/set",
            "image-shift/set",
        ]

    def metadata(self) -> dict[str, Any]:
        out = super().metadata()
        out["capabilities"] = self.capabilities()
        return out

    def get_state_payload(self) -> dict[str, Any]:
        return {
            "connected": self._last_status.get("connected", False),
            "serial_port": self._last_status.get("port"),
            "helper_available": self._last_status.get("ok", False),
        }

    def get_cfg_payload(self) -> dict[str, Any]:
        return dict(self._cfg)

    # ── lifecycle ─────────────────────────────────────────────

    def _start(self) -> None:
        self._refresh_status()
        self._publish_all_retained()
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="ProjectorMonitor", daemon=True,
        )
        self._monitor_thread.start()
        self._log.info("Started component: %s (helper available: %s)",
                       self.component_id, helper_client.ping().get("ok", False))

    def _stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3.0)
            self._monitor_thread = None
        self._log.info("Stopped component: %s", self.component_id)

    def _publish_all_retained(self) -> None:
        self.publish_metadata()
        self.publish_status()
        self.publish_state()
        self.set_telemetry_config({
            "connected": {"enabled": True, "interval_s": 10, "change_threshold_percent": 0},
        })
        self.publish_cfg()

    # ── monitor loop ──────────────────────────────────────────

    def _refresh_status(self) -> None:
        try:
            self._last_status = helper_client.status()
        except Exception:
            self._last_status = {}

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._refresh_status()
                state = self.get_state_payload()
                self.publish_state(state)
                connected = state["connected"]
                if self.should_publish_telemetry("connected", connected):
                    self.publish_telemetry("connected", connected)
            except Exception:
                self._log.exception("Monitor loop error")
            if self._stop_event.wait(self._MONITOR_INTERVAL_S):
                break

    # ── helpers ───────────────────────────────────────────────

    def _parse_payload(self, payload_str: str) -> tuple[dict[str, Any], str]:
        try:
            payload = json.loads(payload_str) if payload_str else {}
            return payload, payload.get("request_id", "")
        except json.JSONDecodeError:
            return {}, ""

    def _send_cmd(
        self, action: str, request_id: str, command: str, value: Optional[int] = None,
    ) -> None:
        """Send a command via the helper daemon and publish the result."""
        result = helper_client.send(command, value)
        ok = result.get("ok", False)
        self.publish_result(action, request_id, ok=ok,
                            error=result.get("error") if not ok else None)

    # ── standard command handlers ─────────────────────────────

    def on_cmd_reset(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        result = helper_client.reset()
        self._refresh_status()
        self.publish_state()
        ok = result.get("ok", False)
        self.publish_result("reset", request_id, ok=ok,
                            error=result.get("error") if not ok else None)

    def on_cmd_ping(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        result = helper_client.ping()
        ok = result.get("ok", False)
        self.publish_result("ping", request_id, ok=ok,
                            error=result.get("error") if not ok else None)

    # ── power commands ────────────────────────────────────────

    def on_cmd_power_on(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("power/on", request_id, "on")

    def on_cmd_power_off(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("power/off", request_id, "off")

    # ── input commands ────────────────────────────────────────

    def on_cmd_input_hdmi1(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("input/hdmi1", request_id, "hdmi1")

    def on_cmd_input_hdmi2(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("input/hdmi2", request_id, "hdmi2")

    # ── aspect ratio commands ─────────────────────────────────

    def on_cmd_aspect_4_3(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("aspect/4-3", request_id, "4:3")

    def on_cmd_aspect_16_9(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("aspect/16-9", request_id, "16:9")

    # ── navigation commands ───────────────────────────────────

    def on_cmd_navigate_up(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/up", request_id, "up")

    def on_cmd_navigate_down(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/down", request_id, "down")

    def on_cmd_navigate_left(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/left", request_id, "left")

    def on_cmd_navigate_right(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/right", request_id, "right")

    def on_cmd_navigate_enter(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/enter", request_id, "enter")

    def on_cmd_navigate_menu(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/menu", request_id, "menu")

    def on_cmd_navigate_back(self, payload_str: str) -> None:
        _, request_id = self._parse_payload(payload_str)
        self._send_cmd("navigate/back", request_id, "back")

    # ── keystone commands ─────────────────────────────────────

    def on_cmd_keystone_set(self, payload_str: str) -> None:
        """Payload: { request_id, axis: "h"|"v", value: int }"""
        payload, request_id = self._parse_payload(payload_str)
        axis = payload.get("axis", "").lower()
        value = payload.get("value")

        if axis not in ("h", "v"):
            self.publish_result("keystone/set", request_id, ok=False,
                                error="'axis' must be 'h' or 'v'")
            return
        if value is None:
            self.publish_result("keystone/set", request_id, ok=False,
                                error="'value' is required")
            return

        command = f"{axis}-keystone"
        self._send_cmd("keystone/set", request_id, command, int(value))

    # ── image shift commands ──────────────────────────────────

    def on_cmd_image_shift_set(self, payload_str: str) -> None:
        """Payload: { request_id, axis: "h"|"v", value: int }"""
        payload, request_id = self._parse_payload(payload_str)
        axis = payload.get("axis", "").lower()
        value = payload.get("value")

        if axis not in ("h", "v"):
            self.publish_result("image-shift/set", request_id, ok=False,
                                error="'axis' must be 'h' or 'v'")
            return
        if value is None:
            self.publish_result("image-shift/set", request_id, ok=False,
                                error="'value' is required")
            return

        command = f"{axis}-image-shift"
        self._send_cmd("image-shift/set", request_id, command, int(value))

    # ── config command ────────────────────────────────────────

    def on_cmd_cfg_set(self, payload_str: str) -> None:
        request_id, set_dict, parse_error = self._parse_cfg_set_payload(payload_str)
        if parse_error:
            self.publish_cfg_set_result(
                request_id=request_id, ok=False, applied=None,
                error=parse_error, ts=_utc_iso(), action="cfg/set",
            )
            return

        applied: dict[str, Any] = {}
        unknown: list[str] = []
        for key, val in set_dict.items():
            if key in self._cfg:
                self._cfg[key] = val
                applied[key] = val
            else:
                unknown.append(key)

        if unknown:
            self.publish_cfg_set_result(
                request_id=request_id, ok=False, applied=applied or None,
                error=f"unknown cfg key(s): {', '.join(sorted(unknown))}",
                ts=_utc_iso(), action="cfg/set",
            )
            return

        self.publish_state()
        self.publish_cfg()
        self.publish_cfg_set_result(
            request_id=request_id, ok=True, applied=applied or None,
            error=None, ts=_utc_iso(), action="cfg/set",
        )
