import unittest
from analyze_rngcaller_dumps import Call
from analyze_tm3_rng_interval import interval_calls

def c(n,before,after):return Call(n,n,0x80028cd4,0x80028ccc,before,after)

class IntervalTests(unittest.TestCase):
    def test_unique_contiguous(self):
        calls=[c(10,1,2),c(11,2,3),c(12,3,4)]
        self.assertEqual(interval_calls(calls,2,4),calls[1:])
    def test_missing_endpoint(self):
        with self.assertRaises(ValueError):interval_calls([c(10,1,2)],1,3)
    def test_ambiguous(self):
        with self.assertRaises(ValueError):interval_calls([c(10,1,2),c(11,1,2)],1,2)
    def test_reseed(self):
        with self.assertRaises(ValueError):interval_calls([c(10,1,2),c(11,3,4)],1,4)
    def test_missing_call(self):
        with self.assertRaises(ValueError):interval_calls([c(10,1,2),c(12,2,3)],1,3)
    def test_equal_endpoints(self):
        with self.assertRaises(ValueError):interval_calls([c(10,1,2)],1,1)

if __name__=='__main__':unittest.main()
