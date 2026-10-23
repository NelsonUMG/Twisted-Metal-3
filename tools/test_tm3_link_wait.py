import unittest
from analyze_tm3_link_wait import records, summarize


class TimingTest(unittest.TestCase):
    line = ('RX_REQUEST ord=7 call=8003AA98 sync=OK wait_us=2000 ready_age_us=50 '
            'worker_gap_max_us=1000 retries=1 send_bytes=36 recv_bytes=36 observed_us=100 ready_us=2050\n')

    def test_parse_and_units(self):
        value = summarize(records(self.line))
        self.assertEqual(value['wait_ms']['p95'], 2)
        self.assertEqual(value['ready_age_ms']['mean'], .05)
        self.assertEqual(value['retries_total'], 1)

    def test_partial_tail_and_old_logs(self):
        self.assertEqual(records(self.line.rstrip()), [])
        self.assertEqual(records('RX_REQUEST ord=7 sync=OK\n'), [])

    def test_invalid(self):
        for bad in ('nan', '-1', 'inf'):
            with self.assertRaises(ValueError):
                records(self.line.replace('wait_us=2000', 'wait_us=' + bad))

    def test_percentile(self):
        rows = records(self.line * 19 + self.line.replace('wait_us=2000', 'wait_us=9000'))
        self.assertEqual(summarize(rows)['wait_ms']['p95'], 2)
        self.assertEqual(summarize(rows)['wait_ms']['max'], 9)


if __name__ == '__main__':
    unittest.main()
