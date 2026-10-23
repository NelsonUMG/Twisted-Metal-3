"""Fixtures for read-only MODE2 extraction and direct MIPS edge decoding."""
from pathlib import Path
import struct
import tempfile
import unittest

from audit_tm3_offline_bin import direct_edge, disc_file


def record(lba, size, name):
    name = name.encode("ascii")
    out = bytearray(33 + len(name) + (len(name) % 2 == 0))
    out[0] = len(out)
    struct.pack_into("<I", out, 2, lba)
    struct.pack_into(">I", out, 6, lba)
    struct.pack_into("<I", out, 10, size)
    struct.pack_into(">I", out, 14, size)
    out[32] = len(name)
    out[33:33 + len(name)] = name
    return out


def sector(payload, form2=False):
    out = bytearray(2352)
    out[:12] = b"\x00" + b"\xff" * 10 + b"\x00"
    out[15] = 2
    out[16:20] = bytes([0, 0, 0x20 if form2 else 8, 0])
    out[20:24] = out[16:20]
    out[24:24 + len(payload)] = payload
    return out


class OfflineAuditTests(unittest.TestCase):
    def fixture(self, folder, form2=False):
        data = bytearray(25 * 2352)
        pvd = bytearray(2048)
        pvd[:7] = b"\x01CD001\x01"
        root = record(20, 4096, "\x00")
        pvd[156:156 + len(root)] = root
        data[16 * 2352:17 * 2352] = sector(pvd)
        data[20 * 2352:21 * 2352] = sector(bytes(2048))
        # Empty directory padding must advance to the next logical sector.
        data[21 * 2352:22 * 2352] = sector(record(23, 2053, "SCUS_942.49;1"))
        payload = bytes(range(256)) * 8 + b"hello"
        data[23 * 2352:24 * 2352] = sector(payload[:2048], form2)
        data[24 * 2352:25 * 2352] = sector(payload[2048:])
        path = Path(folder) / "fixture.bin"
        path.write_bytes(data)
        return path, payload

    def test_extract_multisector_and_directory_padding_without_modifying_disc(self):
        with tempfile.TemporaryDirectory() as folder:
            path, expected = self.fixture(folder)
            before = path.read_bytes()
            actual, info = disc_file(path, "scus_942.49")
            self.assertEqual(actual, expected)
            self.assertEqual(info["bytes"], 2053)
            self.assertEqual(info["lba"], 23)
            self.assertEqual(path.read_bytes(), before)

    def test_form2_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.fixture(folder, True)
            with self.assertRaisesRegex(ValueError, "Form1"):
                disc_file(path, "SCUS_942.49")

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.fixture(folder)
            with self.assertRaisesRegex(ValueError, "missing"):
                disc_file(path, "OTHER.EXE")

    def test_truncated_disc_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "short.bin"
            path.write_bytes(bytes(100))
            with self.assertRaisesRegex(ValueError, "sector"):
                disc_file(path, "SCUS_942.49")

    def test_mips_call_and_tail_jump(self):
        call = direct_edge(0x800146BC, 0x0C004F42)
        self.assertEqual((call["target"], call["kind"]), ("80013D08", "call"))
        jump = direct_edge(0x80013C00, 0x08011E00)
        self.assertEqual((jump["target"], jump["kind"]), ("80047800", "jump"))

    def test_register_call_and_arithmetic_are_not_direct_edges(self):
        self.assertIsNone(direct_edge(0x8004AAE4, 0x0040F809))
        self.assertIsNone(direct_edge(0x8003AF8C, 0x24420001))


if __name__ == "__main__":
    unittest.main()
