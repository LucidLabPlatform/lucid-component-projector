"""Tests for ProjectorSerial and command dictionaries."""
import pytest
from unittest.mock import patch, MagicMock

from lucid_component_projector.serial_conn import (
    STATIC_COMMANDS,
    DYNAMIC_COMMANDS,
    ALL_COMMANDS,
    ProjectorSerial,
    find_usb_serial_device,
)


class TestCommandDictionaries:
    def test_static_commands_all_end_with_cr(self):
        for cmd, ascii_str in STATIC_COMMANDS.items():
            assert ascii_str.endswith("\r"), f"{cmd} does not end with \\r"

    def test_static_commands_all_start_with_tilde(self):
        for cmd, ascii_str in STATIC_COMMANDS.items():
            assert ascii_str.startswith("~"), f"{cmd} does not start with ~"

    def test_dynamic_commands_have_n_placeholder(self):
        for cmd, (template, mn, mx) in DYNAMIC_COMMANDS.items():
            assert "n" in template, f"{cmd} template missing 'n' placeholder"
            assert mn < mx, f"{cmd} min >= max"

    def test_all_commands_is_union(self):
        expected = set(STATIC_COMMANDS.keys()) | set(DYNAMIC_COMMANDS.keys())
        assert set(ALL_COMMANDS) == expected


class TestFindUsbSerialDevice:
    @patch("lucid_component_projector.serial_conn.glob.glob", return_value=[])
    def test_no_devices(self, mock_glob):
        assert find_usb_serial_device() is None

    @patch("lucid_component_projector.serial_conn.glob.glob",
           return_value=["/dev/ttyUSB0", "/dev/ttyUSB1"])
    def test_returns_first(self, mock_glob):
        assert find_usb_serial_device() == "/dev/ttyUSB0"


class TestProjectorSerial:
    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_open_close(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0", baudrate=9600)
        assert not ps.is_open

        ps.open()
        assert ps.is_open
        mock_serial_cls.assert_called_once()

        ps.close()
        mock_ser.close.assert_called_once()

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_static(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()
        ps.send_static("on")
        mock_ser.write.assert_called_with(b"~0000 1\r")

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_static_unknown(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()
        with pytest.raises(KeyError, match="Unknown static command"):
            ps.send_static("nonexistent")

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_dynamic(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()
        ps.send_dynamic("h-keystone", 10)
        mock_ser.write.assert_called_with(b"~0065 10\r")

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_dynamic_out_of_range(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()
        with pytest.raises(ValueError, match="out of range"):
            ps.send_dynamic("h-keystone", 100)

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_dispatches_correctly(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()

        ps.send("off")
        mock_ser.write.assert_called_with(b"~0000 0\r")

        ps.send("v-keystone", -20)
        mock_ser.write.assert_called_with(b"~0066 -20\r")

    @patch("lucid_component_projector.serial_conn.serial.Serial")
    def test_send_dynamic_requires_value(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        ps = ProjectorSerial("/dev/ttyUSB0")
        ps.open()
        with pytest.raises(ValueError, match="requires a 'value' parameter"):
            ps.send("h-keystone")

    def test_write_when_not_open(self):
        ps = ProjectorSerial("/dev/ttyUSB0")
        with pytest.raises(ConnectionError, match="not open"):
            ps.send("on")
