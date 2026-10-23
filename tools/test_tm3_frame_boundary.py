import tempfile
from pathlib import Path
import unittest
from sample_tm3_frame_boundary import category, symbol_rva


class FrameBoundaryTest(unittest.TestCase):
    def test_patched_stubs_override_old_map(self):
        old = {0x80047B00: 'old_SIO_function'}
        self.assertEqual(category(0x80047B00, old), 'BATCH_stub')
        self.assertEqual(category(0x80047798, old), 'DIRECT_stub')
        self.assertEqual(category(0x80047900, old), 'unmapped')
        self.assertEqual(category(0x80047C00, old), 'unmapped')

    def test_exact_pc_mapping_not_function_extent(self):
        table = {0x80013C00: 'sqrt', 0x80013C08: 'sqrt'}
        self.assertEqual(category(0x80013C04, table), 'unmapped')
        self.assertEqual(category(0x80013C08, table), 'sqrt')

    def test_sqrt_codecaves_are_not_transport(self):
        self.assertEqual(category(0x80047820,{},True,True),'sqrt_fast_v2')
        self.assertEqual(category(0x80047B60,{},True,True),'sqrt_pair_v1')
        self.assertEqual(category(0x80047B00,{},True,True),'BATCH_stub')

    def test_unknown_core_refused_before_symbols_or_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            core = Path(temp)/'unknown.dll'
            core.write_bytes(b'not the supported core')
            with self.assertRaisesRegex(ValueError, 'Unsupported core'):
                symbol_rva(core)


if __name__ == '__main__':
    unittest.main()
