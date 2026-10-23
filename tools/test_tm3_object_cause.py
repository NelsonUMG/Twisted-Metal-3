import struct
import tempfile
import unittest
from pathlib import Path
from analyze_tm3_object_cause import MAGIC, RECORD, read_records, network, aligned_interval


def row(seq, time, seed, pc=0x8003AA98):
    values = [0] * 256
    values[1], values[4], values[5], values[6] = pc, time, seed, seq
    return tuple(values)


class ObjectTraceTest(unittest.TestCase):
    def test_frozen_ring_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ring.bin'
            path.write_bytes(struct.pack('<8I', MAGIC, 2, 1024, 2, 3, 0, 3, 2)
                             + RECORD.pack(*row(1, 5, 6)) + RECORD.pack(*row(2, 6, 7)))
            rows, status = read_records(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(status['old_records_evicted'], 1)
            self.assertEqual(status['dump_reason'], 3)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                read_records(path)

    def test_alignment_uses_sequence_not_visit(self):
        tx = {99: {'ordinal': 7, 'time': 2, 'seed': 3}, 500: {'ordinal': 8, 'time': 3, 'seed': 5}}
        event = row(99, 2, 3, 0x80028C7C)
        rows = [row(99, 2, 3), event, row(500, 3, 5)]
        self.assertEqual(aligned_interval(rows, tx, 8), [event])
        with self.assertRaises(ValueError):
            aligned_interval(rows + [rows[-1]], tx, 8)
        with self.assertRaises(ValueError):
            aligned_interval(rows[:-1] + [row(500, 3, 999)], tx, 8)

    def test_network_rejects_reused_sequence_and_partial_tail(self):
        line = 'TX seq=99 ord=7 call=8003AA98 local-time=0x2 local-random=0x3\n'
        self.assertEqual(network(line.rstrip()), ({}, None))
        with self.assertRaises(ValueError):
            network(line + line)
        tx, mismatch = network(line + 'RX_REQUEST ord=7 call=8003AA98 sync=RANDOM_MISMATCH\n')
        self.assertEqual(tx[99]['ordinal'], mismatch)


if __name__ == '__main__':
    unittest.main()
