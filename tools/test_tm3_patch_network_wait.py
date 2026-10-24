import struct
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tm3_patch_network as patch
from patch_system256_transfer_wait import patched_executable


class TransferWaitCallbackTests(unittest.TestCase):
    def test_wait_stub_pumps_only_the_verified_vehicle_transfer_calls(self):
        code = patch.build_stub(mailbox_version=6)
        words = struct.unpack('<%dI' % (len(code) // 4), code)
        self.assertLessEqual(len(code), patch.MAILBOX_ADDRESS - patch.FUNCTION_START)
        self.assertIn(patch.i_type(0x0D, patch.REG['t2'], patch.REG['t2'], 0x7EA0), words)
        self.assertIn(patch.i_type(0x09, patch.REG['t2'], patch.REG['t2'], 0x18), words)
        self.assertIn(patch.i_type(0x23, patch.REG['s1'], patch.REG['v0'], 8), words)
        self.assertIn(patch.r_type(patch.REG['v0'], 0, patch.REG['ra'], 0, 9), words)
        self.assertIn(patch.i_type(0x23, patch.REG['sp'], patch.REG['ra'], 12), words)
        self.assertIn(patch.i_type(0x2B, patch.REG['sp'], patch.REG['a2'], 0), words)
        self.assertIn(patch.i_type(0x2B, patch.REG['sp'], patch.REG['a3'], 4), words)
        self.assertIn(patch.i_type(0x23, patch.REG['sp'], patch.REG['a2'], 0), words)
        self.assertIn(patch.i_type(0x23, patch.REG['sp'], patch.REG['a3'], 4), words)

    def test_abi6_image_keeps_mailbox_and_callbacks_while_patching_stub(self):
        executable = bytearray(0xA0000)
        executable[:8] = b'PS-X EXE'
        struct.pack_into('<I', executable, 0x18, patch.TEXT_ADDRESS)
        expected = {
            0x80047728: 0x3C080001,
            0x80047D48: 0x3C02800D,
            0x80047D4C: 0x24423280,
            0x80047D54: 0x00408821,
            0x80047E98: patch.j_type(0x03, patch.FUNCTION_START),
            0x80047EB0: patch.j_type(0x03, patch.FUNCTION_START),
        }
        for address, value in expected.items():
            struct.pack_into('<I', executable,
                0x800 + address - patch.TEXT_ADDRESS, value)
        struct.pack_into('<I', executable,
            0x800 + patch.MAILBOX_ADDRESS - patch.TEXT_ADDRESS, patch.MAILBOX_MAGIC)
        struct.pack_into('<I', executable,
            0x800 + patch.MAILBOX_ADDRESS + 4 - patch.TEXT_ADDRESS, 6)
        result, code_size = patched_executable(bytes(executable))
        self.assertEqual(code_size, len(patch.build_stub(mailbox_version=6)))
        self.assertEqual(struct.unpack_from('<I', result,
            0x800 + patch.MAILBOX_ADDRESS - patch.TEXT_ADDRESS)[0], patch.MAILBOX_MAGIC)
        self.assertEqual(struct.unpack_from('<I', result,
            0x800 + patch.MAILBOX_ADDRESS + 4 - patch.TEXT_ADDRESS)[0] & 0xFFFF, 6)


if __name__ == '__main__':
    unittest.main()
