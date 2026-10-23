import unittest
from diagnose_tm3_slowdown import analyze


class DiagnosticTest(unittest.TestCase):
    perf = (b'elapsed_s,window_s,completed_total,core_frames,time_steps,time_discontinuities,core_ms_mean,paint_ms,core_ms_max\n'
            b'1,1,1,60,20,0,8,30,12\n2,1,2,60,20,0,8,30,12\n')
    trace = (b'RX_REQUEST seq=2 ord=2 call=8003AA98 sync=OK wait_us=6000 ready_age_us=1000 '
             b'worker_gap_max_us=2000 retries=0 send_bytes=36 recv_bytes=36 observed_us=10000 ready_us=15000\n')

    def test_decomposition_and_boundaries(self):
        r = analyze(self.perf, self.trace, 1, 2)
        self.assertTrue(r['valid'])
        self.assertEqual(r['before_remote_available_ms_mean'], 5)
        self.assertEqual(r['after_both_available_ms_mean'], 1)
        self.assertEqual(r['time_units_per_s'], 20)

    def test_early_remote(self):
        r = analyze(self.perf, self.trace.replace(b'ready_us=15000', b'ready_us=9000'), 1, 2)
        self.assertEqual(r['before_remote_available_ms_mean'], 0)
        self.assertEqual(r['after_both_available_ms_mean'], 6)

    def test_partial_duplicate_and_missing(self):
        for trace in (self.trace.rstrip(), self.trace*2, b''):
            self.assertFalse(analyze(self.perf, trace, 1, 2)['valid'])

    def test_transition_and_mismatch(self):
        self.assertFalse(analyze(self.perf.replace(b'2,1,2,60,20,0', b'2,1,2,60,20,1'), self.trace, 1, 2)['valid'])
        self.assertFalse(analyze(self.perf, self.trace.replace(b'sync=OK', b'sync=TIME_MISMATCH'), 1, 2)['valid'])

    def test_menu_not_gameplay(self):
        self.assertFalse(analyze(self.perf, self.trace.replace(b'call=8003AA98', b'call=80000000'), 1, 2)['valid'])


if __name__ == '__main__':
    unittest.main()
