import struct
import tempfile
import unittest
from pathlib import Path
from analyze_tm3_lifecycle import read_trace, describe


class LifecycleTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'trace.bin'
            p.write_bytes(data)
            return read_trace(p)

    def test_records_and_partial_tail(self):
        r = [0]*128
        r[0], r[1], r[3], r[4], r[41], r[52] = 3, 0x800444C8, 2, 99, 0x80036344, 1
        rows, status = self.parse(struct.pack('<4I', 0x31434C54, 1, 512, 1048576)+struct.pack('<128I', *r)+b'tail')
        self.assertEqual(status['partial_tail_bytes'], 4)
        self.assertEqual(len(rows), 1)
        d = describe(rows[0])
        self.assertEqual(d['ra'], '80036344')
        self.assertEqual(d['globals']['victory'], 1)
        self.assertEqual(d['pending_load']['value'], '00000063')

    def test_bad_header(self):
        for data in (b'', struct.pack('<4I', 0x31434C54, 2, 512, 4), struct.pack('<4I', 0x31434C54, 1, 512, 0)):
            with self.assertRaises(ValueError): self.parse(data)

    def test_bad_record(self):
        with self.assertRaises(ValueError):
            self.parse(struct.pack('<4I', 0x31434C54, 1, 512, 4)+bytes(512))


if __name__ == '__main__': unittest.main()
