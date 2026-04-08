"""Contract tests for ProjectorComponent: lifecycle, state, commands."""
import json
from unittest.mock import patch, MagicMock

import pytest
from lucid_component_base import ComponentContext, ComponentStatus

from lucid_component_projector import ProjectorComponent


class RecordingMQTT:
    def __init__(self):
        self.calls: list[dict] = []

    def publish(self, topic: str, payload, *, qos: int = 0, retain: bool = False) -> None:
        self.calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})

    def last_payload_for(self, suffix: str) -> dict | None:
        for c in reversed(self.calls):
            if c["topic"].endswith(suffix):
                return json.loads(c["payload"])
        return None


def _make(cfg: dict | None = None) -> tuple[ProjectorComponent, RecordingMQTT]:
    mqtt = RecordingMQTT()
    ctx = ComponentContext.create(
        agent_id="test-agent",
        base_topic="lucid/agents/test-agent",
        component_id="projector",
        mqtt=mqtt,
        config=cfg or {},
    )
    return ProjectorComponent(ctx), mqtt


# ── identity ──────────────────────────────────────────────────


def test_component_id():
    comp, _ = _make()
    assert comp.component_id == "projector"


def test_initial_status():
    comp, _ = _make()
    assert comp.state.status == ComponentStatus.STOPPED


def test_capabilities():
    comp, _ = _make()
    caps = comp.capabilities()
    assert "power/on" in caps
    assert "power/off" in caps
    assert "input/hdmi1" in caps
    assert "input/hdmi2" in caps
    assert "aspect/4-3" in caps
    assert "aspect/16-9" in caps
    assert "navigate/up" in caps
    assert "navigate/enter" in caps
    assert "navigate/menu" in caps
    assert "navigate/back" in caps
    assert "keystone/set" in caps
    assert "image-shift/set" in caps
    assert "reset" in caps
    assert "ping" in caps


def test_metadata_includes_capabilities():
    comp, _ = _make()
    meta = comp.metadata()
    assert meta["component_id"] == "projector"
    assert "capabilities" in meta
    assert "power/on" in meta["capabilities"]


# ── lifecycle ─────────────────────────────────────────────────


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_start_stop_lifecycle(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    assert comp.state.status == ComponentStatus.RUNNING
    assert comp.state.started_at is not None

    comp.stop()
    assert comp.state.status == ComponentStatus.STOPPED
    assert comp.state.stopped_at is not None
    mock_ser.close.assert_called_once()


@patch("lucid_component_projector.component.find_usb_serial_device", return_value=None)
def test_start_fails_no_serial(mock_find):
    comp, _ = _make()
    with pytest.raises(RuntimeError, match="No serial port"):
        comp.start()
    assert comp.state.status == ComponentStatus.FAILED


@patch("lucid_component_projector.component.ProjectorSerial")
def test_start_with_configured_port(mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB1"
    mock_serial_cls.return_value = mock_ser

    comp, _ = _make(cfg={"serial_port": "/dev/ttyUSB1"})
    comp.start()
    mock_serial_cls.assert_called_once_with(
        port="/dev/ttyUSB1", baudrate=9600, timeout=1.0,
    )
    comp.stop()


# ── state & config ────────────────────────────────────────────


def test_get_state_payload_not_connected():
    comp, _ = _make()
    state = comp.get_state_payload()
    assert state["connected"] is False
    assert state["serial_port"] is None


def test_get_cfg_payload():
    comp, _ = _make(cfg={"baudrate": 19200})
    cfg = comp.get_cfg_payload()
    assert cfg["baudrate"] == 19200
    assert cfg["serial_port"] == ""


# ── command handlers ──────────────────────────────────────────


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_power_on(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_power_on(json.dumps({"request_id": "r1"}))

    mock_ser.send.assert_called_with("on", None)
    result = mqtt.last_payload_for("evt/power/on/result")
    assert result["request_id"] == "r1"
    assert result["ok"] is True
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_power_off(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_power_off(json.dumps({"request_id": "r2"}))

    mock_ser.send.assert_called_with("off", None)
    result = mqtt.last_payload_for("evt/power/off/result")
    assert result["ok"] is True
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_navigate_enter(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_navigate_enter(json.dumps({"request_id": "r3"}))

    mock_ser.send.assert_called_with("enter", None)
    result = mqtt.last_payload_for("evt/navigate/enter/result")
    assert result["ok"] is True
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_keystone_set(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_keystone_set(json.dumps({
        "request_id": "r4", "axis": "h", "value": -10,
    }))

    mock_ser.send.assert_called_with("h-keystone", -10)
    result = mqtt.last_payload_for("evt/keystone/set/result")
    assert result["ok"] is True
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_keystone_set_missing_axis(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_keystone_set(json.dumps({"request_id": "r5", "value": 10}))

    result = mqtt.last_payload_for("evt/keystone/set/result")
    assert result["ok"] is False
    assert "axis" in result["error"]
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_image_shift_set(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_image_shift_set(json.dumps({
        "request_id": "r6", "axis": "v", "value": 50,
    }))

    mock_ser.send.assert_called_with("v-image-shift", 50)
    result = mqtt.last_payload_for("evt/image-shift/set/result")
    assert result["ok"] is True
    comp.stop()


def test_command_when_not_connected():
    comp, mqtt = _make()
    # Don't start — serial is None
    comp.on_cmd_power_on(json.dumps({"request_id": "r7"}))
    result = mqtt.last_payload_for("evt/power/on/result")
    assert result["ok"] is False
    assert "not connected" in result["error"]


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_serial_error_returns_failure(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_ser.send.side_effect = OSError("device disconnected")
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_power_on(json.dumps({"request_id": "r8"}))

    result = mqtt.last_payload_for("evt/power/on/result")
    assert result["ok"] is False
    assert "disconnected" in result["error"]
    comp.stop()


# ── ping & reset ──────────────────────────────────────────────


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_ping(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_ping(json.dumps({"request_id": "rp"}))
    result = mqtt.last_payload_for("evt/ping/result")
    assert result["ok"] is True
    comp.stop()


@patch("lucid_component_projector.component.ProjectorSerial")
@patch("lucid_component_projector.component.find_usb_serial_device", return_value="/dev/ttyUSB0")
def test_reset_reconnects(mock_find, mock_serial_cls):
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.port = "/dev/ttyUSB0"
    mock_serial_cls.return_value = mock_ser

    comp, mqtt = _make()
    comp.start()
    comp.on_cmd_reset(json.dumps({"request_id": "rr"}))

    mock_ser.close.assert_called()
    mock_ser.open.assert_called()
    result = mqtt.last_payload_for("evt/reset/result")
    assert result["ok"] is True
    comp.stop()
