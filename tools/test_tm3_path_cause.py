import unittest
from unittest.mock import patch
import analyze_tm3_path_cause as analyzer


class PathTraceTests(unittest.TestCase):
    def record(self, pc=0x80017148, instruction=0x90A2000B):
        r = [0] * 64
        r[0], r[1], r[3], r[10] = 3, pc, 5, instruction
        r[11], r[12], r[13] = 0x8010000B, 1, 0x12340001
        return r

    def compare(self, a, b):
        with patch.object(analyzer, 'iter_trace', side_effect=[iter(a), iter(b)]):
            return analyzer.compare_paths('left', 'right', 5)

    def test_equal(self):
        self.assertEqual(self.compare([self.record()], [self.record()])['instructions_each'], 1)

    def test_unconsumed_bytes_ignored(self):
        a, b = self.record(), self.record()
        b[13] = 0xABCD0001
        self.assertEqual(self.compare([a], [b])['instructions_each'], 1)

    def test_eligibility_difference(self):
        a, b = self.record(), self.record()
        b[13] = 0
        self.assertIn('unequal memory', self.compare([a], [b])['reason'])

    def test_branch_path_difference(self):
        self.assertIn('instruction sequence', self.compare(
            [self.record()], [self.record(pc=0x80017420)])['reason'])

    def test_missing_records(self):
        self.assertEqual(self.compare([], [self.record()])['extra_side'], 'Sofia')

    def test_search_inputs(self):
        a, b = self.record(pc=0x80016EA8), self.record(pc=0x80016EA8)
        b[21] = 7
        self.assertIn('search entry', self.compare([a], [b])['reason'])

    def test_repeated_preexecution_pc(self):
        a = self.record()
        self.assertEqual(self.compare([a, a], [a])['instructions_each'], 1)

    def test_boundary_visits_map_to_protocol(self):
        a, b = self.record(), self.record()
        a[0] = b[0] = 1
        a[3], b[3] = 2541, 2542
        a[15] = b[15] = 2540
        a[7] = b[7] = 0x4065DFAD
        with patch.object(analyzer, 'iter_trace', return_value=iter([a, b])):
            boundaries, count, mapping, repeated = analyzer.scan_trace(
                'ignored', {(2540, 0x4065DFAD): {2541}})
        self.assertEqual(count, 2)
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(mapping, {2541: 2541, 2542: 2541})
        self.assertEqual(repeated, 1)


if __name__ == '__main__':
    unittest.main()
