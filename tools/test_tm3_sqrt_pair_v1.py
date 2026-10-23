"""Differential real-MIPS replay. No GPU/interrupt/whole-game claim."""
import json
import random
import unittest
import tm3_patch_sqrt_pair_v1 as patch

MASK=0xffffffff
STOP=0x80000080
def signed(v): return v-(1<<32) if v&0x80000000 else v

def replay(blob, regs, start=0x80013C00):
    r=regs.copy(); pc=start; next_pc=pc+4; pending=None; lzcs=lzcr=0
    for steps in range(20000):
        if pc==STOP: return r,(lzcs,lzcr),steps
        w=patch.word(blob,pc); op=w>>26; rs=(w>>21)&31; rt=(w>>16)&31
        rd=(w>>11)&31; sh=(w>>6)&31; fn=w&63; n=w&65535
        imm=n-65536 if n&32768 else n
        following=next_pc+4; dest=None; value=0; load=None
        if op==0:
            if fn==0: dest,value=rd,r[rt]<<sh
            elif fn==2: dest,value=rd,r[rt]>>sh
            elif fn==3: dest,value=rd,signed(r[rt])>>sh
            elif fn==4: dest,value=rd,r[rt]<<(r[rs]&31)
            elif fn==6: dest,value=rd,r[rt]>>(r[rs]&31)
            elif fn==8: following=r[rs]
            elif fn==0x21: dest,value=rd,r[rs]+r[rt]
            elif fn in (0x22,0x23):
                dest,value=rd,r[rs]-r[rt]
                if fn==0x22 and not -(1<<31)<=signed(r[rs])-signed(r[rt])<(1<<31):
                    raise OverflowError('Original SUB overflow')
            elif fn==0x25: dest,value=rd,r[rs]|r[rt]
            elif fn==0x2a: dest,value=rd,int(signed(r[rs])<signed(r[rt]))
            else: raise ValueError(hex(w))
        elif op==9: dest,value=rt,r[rs]+imm
        elif op==12: dest,value=rt,r[rs]&n
        elif op==5:
            if r[rs]!=r[rt]: following=pc+4+4*imm
        elif op==2: following=((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
        elif w==0x4884F000:
            lzcs=r[4]; x=lzcs if lzcs<0x80000000 else lzcs^MASK
            lzcr=32-x.bit_length()
        elif w==0x480BF800: load=(11,lzcr)
        else: raise ValueError(f'{pc:08X}: {w:08X}')
        if pending: r[pending[0]]=pending[1]
        if dest: r[dest]=value&MASK
        r[0]=0; pending=load; pc,next_pc=next_pc,following
    raise ValueError('Replay exceeded bounded domain')

class SqrtPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=patch.SOURCE.read_bytes()
        cls.candidate,cls.ips,cls.meta=patch.build(cls.source)
        cls.random=random.Random(0x13C00)

    def check(self,a,b,precision,start=0x80013C00):
        regs=[0]+[self.random.getrandbits(32) for _ in range(31)]
        regs[4:7]=[a,b,precision]; regs[31]=STOP
        old=replay(self.source,regs,start); new=replay(self.candidate,regs,start)
        self.assertEqual(old[:2],new[:2],(a,b,precision,start))
        return old[2],new[2]

    def test_boundaries_and_random_full_function(self):
        edges=[0,1,2,3,0x7fffffff,0x80000000,0xfffffffe,0xffffffff]
        edges+=list({x for bit in range(32) for x in ((1<<bit)-1,1<<bit,(1<<bit)+1)})
        totals=[0,0]; cases=0
        for a in edges:
            for b in (0,1,0x7fffffff,0xffffffff):
                for precision in (0,1,2,12,32,64):
                    counts=self.check(a,b,precision); cases+=1
                    totals=[x+y for x,y in zip(totals,counts)]
        for _ in range(3000):
            counts=self.check(self.random.getrandbits(32),self.random.getrandbits(32),self.random.randrange(65))
            totals=[x+y for x,y in zip(totals,counts)]; cases+=1
        print(json.dumps({'full_function_cases':cases,'synthetic_dispatch_totals':totals,
                          'note':'Synthetic input mix, not measured game speed'}))

    def test_arbitrary_loop_state_both_parities(self):
        for n in range(1,129):
            for _ in range(8):
                self.check(self.random.getrandbits(32),self.random.getrandbits(32),n,patch.HOOK)

    def test_count_reduction(self):
        for n in range(1,65):
            old,new=self.check(0x12345678,0x87654321,n,patch.HOOK)
            # Five entry instructions overhead; two removed for every complete pair.
            self.assertEqual(old-new,2*(n//2)-5)

    def test_scope_and_refusal(self):
        self.assertEqual(patch.replay_ips(self.source,self.ips),self.candidate)
        allowed=set(range(patch.at(patch.HOOK),patch.at(patch.HOOK)+8))
        allowed.update(range(patch.at(patch.CAVE),patch.at(patch.CAVE)+self.meta['helper_bytes']))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.source,self.candidate))))
        for bad in (self.candidate,self.source[:-1],bytes(len(self.source))):
            with self.assertRaises(ValueError): patch.build(bad)

if __name__=='__main__': unittest.main()
