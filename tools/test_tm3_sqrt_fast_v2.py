"""Differential replay of actual patch words; bounded, not whole-game emulation."""
import math
import random
import unittest
import tm3_patch_sqrt_fast_v2 as patch
from test_tm3_sqrt_pair_v1 import replay,STOP

class FastSqrtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=patch.SOURCE.read_bytes();cls.new,cls.ips,cls.meta=patch.build(cls.source)
        cls.rng=random.Random(0x47800)
    def check(self,hi,lo,precision):
        regs=[0]+[self.rng.getrandbits(32) for _ in range(31)]
        regs[4:7]=[hi,lo,precision];regs[31]=STOP
        old=replay(self.source,regs);new=replay(self.new,regs)
        self.assertEqual(old[:2],new[:2],(hi,lo,precision))
        if hi==0 and precision==0:self.assertEqual(new[0][2],math.isqrt(lo))
        return old[2],new[2]
    def test_fast_path_edges_and_random(self):
        values=set(range(256))|{0xffffffff,0x80000000,0x7fffffff}
        for k in list(range(256))+list(range(65280,65536)):
            values.update(v for v in (k*k-1,k*k,k*k+1) if 0<=v<=0xffffffff)
        for bit in range(32):values.update(((1<<bit)-1,1<<bit,(1<<bit)+1))
        values.update(self.rng.getrandbits(32) for _ in range(4096))
        totals=[0,0]
        for v in sorted(values):
            counts=self.check(0,v,0);totals=[a+b for a,b in zip(totals,counts)]
            self.assertLess(counts[1],counts[0])
        print({'fast_cases':len(values),'old_new_dispatches':totals})
    def test_fallback(self):
        for hi in (0,1,0x7fffffff,0x80000000,0xffffffff):
            for precision in (0,1,2,12,32,64):
                if hi==0 and precision==0:continue
                for _ in range(32):self.check(hi,self.rng.getrandbits(32),precision)
    def test_exact_scope_and_refusal(self):
        self.assertEqual(patch.base.replay_ips(self.source,self.ips),self.new)
        allowed=set(range(patch.at(patch.HOOK),patch.at(patch.HOOK)+8))
        allowed.update(range(patch.at(patch.CAVE),patch.at(patch.CAVE)+self.meta['helper_bytes']))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.source,self.new))))
        for bad in (self.new,self.source[:-1],bytes(len(self.source))):
            with self.assertRaises(ValueError):patch.build(bad)
if __name__=='__main__':unittest.main()
