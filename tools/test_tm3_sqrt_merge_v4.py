"""Bounded real MIPS differential tests of fused general-root input shifts."""
import random
import unittest
import tm3_patch_sqrt_merge_v4 as patch
from test_tm3_sqrt_pair_v1 import replay,STOP

class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=patch.SOURCE.read_bytes();cls.new,cls.ips,cls.meta=patch.build(cls.source)

    def check(self,r,start=0x80013C00):
        old=replay(self.source,r,start);new=replay(self.new,r,start)
        self.assertEqual(old[:2],new[:2],(r[4:7],start))
        return old[2],new[2]

    def test_full_function(self):
        rng=random.Random(0x47B50)
        edges=[0,1,2,3,0x7fffffff,0x80000000,0xfffffffe,0xffffffff]
        edges+=sorted({v for bit in range(1,32) for v in ((1<<bit)-1,1<<bit,(1<<bit)+1)})
        cases=[(hi,lo,p) for hi in edges for lo in (0,1,0x7fffffff,0xffffffff) for p in (0,1,2,12,31,32,63,64)]
        cases += [(rng.getrandbits(32),rng.getrandbits(32),rng.randrange(65)) for _ in range(8192)]
        totals=[0,0];regressions=0
        for hi,lo,p in cases:
            r=[0]+[rng.getrandbits(32) for _ in range(31)];r[4:7]=[hi,lo,p];r[31]=STOP
            counts=self.check(r);totals=[a+b for a,b in zip(totals,counts)]
            regressions+=counts[1]>counts[0]
            if hi==0 and p==0:self.assertEqual(*counts)
        print({'full_cases':len(cases),'synthetic_dispatch_totals':totals,'regressions':regressions})

    def test_arbitrary_loop_states(self):
        rng=random.Random(44);deltas={}
        for count in range(1,129):
            for _ in range(16):
                r=[0]+[rng.getrandbits(32) for _ in range(31)];r[6]=count;r[31]=STOP
                old,new=self.check(r,patch.base.HOOK);deltas[count]=old-new
        print({'dispatch_saving_by_count':{n:deltas[n] for n in (1,2,3,16,17,22,31,32,64,128)}})

    def test_scope_and_refusal(self):
        self.assertEqual(patch.base.replay_ips(self.source,self.ips),self.new)
        allowed=set(range(patch.base.at(patch.base.HOOK),patch.base.at(patch.base.HOOK)+4))
        allowed.update(range(patch.base.at(patch.CAVE),patch.base.at(patch.base.LIMIT)))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.source,self.new))))
        for bad in (self.new,self.source[:-1],bytes(len(self.source))):
            with self.assertRaises(ValueError):patch.build(bad)

    def test_against_pre_sqrt_optimization(self):
        original=patch.base.SOURCE.read_bytes();rng=random.Random(7654)
        for _ in range(1024):
            r=[0]+[rng.getrandbits(32) for _ in range(31)]
            r[6]=rng.randrange(65);r[31]=STOP
            self.assertEqual(replay(original,r)[:2],replay(self.new,r)[:2])

if __name__=='__main__':unittest.main()
