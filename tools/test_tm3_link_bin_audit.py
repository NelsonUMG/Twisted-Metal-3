import unittest
from audit_tm3_link_bin import timing

class TimingTests(unittest.TestCase):
    def row(self,observed,ready,wait):
        return dict(seq='1',observed_us=observed,ready_us=ready,wait_us=wait,
                    retries=0,send_bytes=36,recv_bytes=36)
    def test_remote_later(self):
        r=timing([self.row(1000,3000,2050)])
        self.assertEqual(r['before_remote_ready_mean_ms'],2)
        self.assertEqual(r['after_remote_ready_mean_ms'],.05)
    def test_remote_already_ready(self):
        r=timing([self.row(3000,1000,100)])
        self.assertEqual(r['before_remote_ready_mean_ms'],0)
        self.assertEqual(r['after_remote_ready_mean_ms'],.1)
    def test_empty(self):self.assertEqual(timing([]),{'count':0})

if __name__=='__main__':unittest.main()
