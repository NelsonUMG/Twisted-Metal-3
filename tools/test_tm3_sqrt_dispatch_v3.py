"""Actual MIPS differential replay; no game is launched."""
import random
import unittest
import tm3_patch_sqrt_dispatch_v3 as patch
from test_tm3_sqrt_pair_v1 import replay,STOP

class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=patch.SOURCE.read_bytes()
        cls.candidate,cls.ips,cls.meta=patch.build(cls.source)

    def test_equivalence_and_exact_dispatch_saving(self):
        rng=random.Random(0x478E4)
        edges=[0,1,2,3,0x7fffffff,0x80000000,0xfffffffe,0xffffffff]
        cases=[(hi,lo,p) for hi in edges for lo in edges for p in (0,1,2,12,31,32,63,64)]
        cases += [(rng.getrandbits(32),rng.getrandbits(32),rng.randrange(65)) for _ in range(4096)]
        for hi,lo,p in cases:
            regs=[0]+[rng.getrandbits(32) for _ in range(31)]
            regs[4:7]=[hi,lo,p];regs[31]=STOP
            old=replay(self.source,regs);new=replay(self.candidate,regs)
            self.assertEqual(old[:2],new[:2],(hi,lo,p))
            self.assertEqual(old[2]-new[2],0 if hi==0 and p==0 else 2)
        print({'cases':len(cases),'checks':'all GPR, LZCS/LZCR, exact dispatch delta'})

    def test_loop_entry_parities(self):
        rng=random.Random(123)
        for count in range(1,129):
            regs=[0]+[rng.getrandbits(32) for _ in range(31)]
            regs[6]=count;regs[31]=STOP
            old=replay(self.source,regs,0x80013C3C)
            new=replay(self.candidate,regs,0x80013C3C)
            self.assertEqual(old[:2],new[:2])
            self.assertEqual(old[2]-new[2],1)

    def test_scope_and_refusal(self):
        self.assertEqual(patch.base.replay_ips(self.source,self.ips),self.candidate)
        allowed={patch.base.at(int(p,16))+i for p in self.meta['instruction_addresses'] for i in range(4)}
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.source,self.candidate))))
        for bad in (self.candidate,self.source[:-1],bytes(len(self.source))):
            with self.assertRaises(ValueError):patch.build(bad)

if __name__=='__main__':unittest.main()
