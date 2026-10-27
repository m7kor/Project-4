import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("pcsx2_reference",
    Path(__file__).resolve().parents[1] / "tools/diagnostics/pcsx2_reference.py")
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)


class Wire:
    def __init__(self, payload=b"", status=0, length=None):
        self.reply = bytearray(struct.pack("<I", len(payload) + 5 if length is None else length)
                               + bytes([status]) + payload)
        self.sent = bytearray()

    def sendall(self, value):
        self.sent.extend(value)

    def recv(self, size):
        size = min(size, 2, len(self.reply))
        value = bytes(self.reply[:size])
        del self.reply[:size]
        return value


class Paused:
    def __init__(self, changed_memory=False, changed_identity=False):
        self.reads = 0
        self.identities = 0
        self.changed_memory = changed_memory
        self.changed_identity = changed_identity

    def identity(self):
        self.identities += 1
        return {"serial": "SLUS-21134", "crc": "12345678",
                "version": "changed" if self.changed_identity and self.identities > 1 else "test"}

    def read(self, address, size):
        self.reads += 1
        return bytes([1 if self.changed_memory and self.reads > 1 else 0]) * size


class ReferenceTests(unittest.TestCase):
    def test_inspect_uses_pcsx2_default_slot(self):
        with patch("sys.argv", ["reference", "--inspect"]), patch.object(reference.socket, "create_connection") as connect:
            with patch.object(reference.Pine, "identity", return_value={"serial": "SLUS-21134"}), patch("builtins.print"):
                reference.main()
            connect.assert_called_once_with(("127.0.0.1", 28011), timeout=5)

    def test_existing_output_rejected_before_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference.json"
            output.write_text("keep", encoding="utf-8")
            arguments = ["reference", "--crc", "12345678", "--window", "0x100:4", "--out", str(output)]
            with patch("sys.argv", arguments), patch.object(reference.socket, "create_connection") as connect:
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    reference.main()
                connect.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_invalid_crc_rejected_before_connection(self):
        arguments = ["reference", "--crc", "not-a-crc", "--window", "0x100:4", "--out", "unused.json"]
        with patch("sys.argv", arguments), patch.object(reference.socket, "create_connection") as connect:
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                reference.main()
            connect.assert_not_called()

    def test_fragmented_read_uses_only_read32(self):
        wire = Wire(struct.pack("<2I", 42, 71))
        self.assertEqual(reference.Pine(wire).read(0x100, 8), struct.pack("<2I", 42, 71))
        self.assertEqual(wire.sent, struct.pack("<I", 14) + b"\x02\x00\x01\x00\x00\x02\x04\x01\x00\x00")

    def test_ranges_rejected_before_network(self):
        for address, size in [(-4, 4), (1, 4), (0, 3), (0, 0), (0, 65540), (reference.RAM_BYTES, 4)]:
            wire = Wire()
            with self.assertRaises(ValueError):
                reference.Pine(wire).read(address, size)
            self.assertFalse(wire.sent)

    def test_malformed_and_rejected_replies(self):
        for wire in [Wire(length=4), Wire(length=1000000), Wire(status=255), Wire(b"x")]:
            with self.assertRaises(ValueError):
                reference.Pine(wire).read(0, 4)
        with self.assertRaises(EOFError):
            reference.Pine(Wire(length=9)).read(0, 4)

    def test_pause_required(self):
        wire = Wire(struct.pack("<I", 0))
        with self.assertRaisesRegex(ValueError, "Pause"):
            reference.Pine(wire).identity()
        self.assertEqual(wire.sent, struct.pack("<I", 5) + b"\x0f")

    def test_identity_strings_are_bounded_and_terminated(self):
        for payload in [b"", struct.pack("<I", 2) + b"ab", struct.pack("<I", 9) + b"ab\0"]:
            with self.assertRaises(ValueError):
                reference.Pine(Wire(payload)).text(12)
        wire = Wire()
        with self.assertRaises(ValueError):
            reference.Pine(wire).text(4)
        self.assertFalse(wire.sent)

    def test_wrong_game_and_crc_stop_before_memory(self):
        for serial, crc in [("SCUS-97399", "12345678"), ("SLUS-21134", "87654321")]:
            pine = Paused()
            with self.assertRaises(ValueError):
                reference.capture(pine, serial, crc, [(0x100, 4)])
            self.assertEqual(pine.reads, 0)

    def test_unstable_reference_rejected(self):
        for pine in [Paused(changed_memory=True), Paused(changed_identity=True)]:
            with self.assertRaises(ValueError):
                reference.capture(pine, "SLUS-21134", "12345678", [(0x100, 4)])

    def test_stable_capture_keeps_exact_address_bytes_and_limit(self):
        result = reference.capture(Paused(), "SLUS-21134", "12345678", [(0x100, 4)])
        self.assertEqual(result["windows"][0]["address"], "0x100")
        self.assertEqual(result["windows"][0]["bytes_hex"], "00000000")
        self.assertIn("checkpoint", result["limitation"])
        for windows in [[], [(0, 4)] * 65, [(0, 65536)] * 17]:
            with self.assertRaises(ValueError):
                reference.capture(Paused(), "SLUS-21134", "12345678", windows)


if __name__ == "__main__":
    unittest.main()
