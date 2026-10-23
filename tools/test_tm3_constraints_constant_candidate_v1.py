"""Bounded real-MIPS differential checks at the three callsite windows."""
import random
import unittest
from audit_tm3_offline_bin import ROOT,disc_file,word
import tm3_constraints_constant_candidate_v1 as patch

MASK=0xFFFFFFFF
def signed(n):return n-(1<<32) if n>>31 else n


def replay(blob,start,input_value):
    # Implements original JAL + delay slot + MULT/HI/LO helper and inline words.
    regs=[0]+[0xDA000000+i for i in range(1,32)]
    regs[2]=input_value&MASK
    pc,next_pc=start,start+4
    hi=0x12345678;lo=0x87654321
    for dispatch in range(100):
        if pc==start+16:return regs,hi,lo,dispatch
        w=word(blob,pc);op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31
        rd=(w>>11)&31;sh=(w>>6)&31;fn=w&63;imm=w&65535
        simm=imm-65536 if imm&32768 else imm
        following=next_pc+4;dest=None;value=0
        if op==0:
            if fn==0:dest,value=rd,regs[rt]<<sh
            elif fn==2:dest,value=rd,regs[rt]>>sh
            elif fn==3:dest,value=rd,signed(regs[rt])>>sh
            elif fn==4:dest,value=rd,regs[rt]<<(regs[rs]&31)
            elif fn==6:dest,value=rd,regs[rt]>>(regs[rs]&31)
            elif fn==8:following=regs[rs]
            elif fn==0x18:
                product=(signed(regs[rs])*signed(regs[rt]))&((1<<64)-1)
                hi,lo=product>>32,product&MASK
            elif fn==0x10:dest,value=rd,hi
            elif fn==0x12:dest,value=rd,lo
            elif fn==0x21:dest,value=rd,regs[rs]+regs[rt]
            elif fn==0x23:dest,value=rd,regs[rs]-regs[rt]
            elif fn==0x25:dest,value=rd,regs[rs]|regs[rt]
            else:raise ValueError(f'Unsupported {w:08X}')
        elif op==3:
            dest,value=31,pc+8
            following=((pc+4)&0xF0000000)|((w&0x3FFFFFF)<<2)
        elif op==9:dest,value=rt,regs[rs]+simm
        elif op==12:dest,value=rt,regs[rs]&imm
        else:raise ValueError(f'Unsupported {w:08X}')
        if dest:regs[dest]=value&MASK
        regs[0]=0;pc,next_pc=next_pc,following
    raise ValueError('Window did not return')


class ConstantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,_=disc_file(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin','SCUS_942.49')
        cls.candidate=patch.build(cls.source)

    def test_exact_scope_refusal(self):
        allowed={patch.offset(pc)+i for pc in patch.SITES for i in range(16)}
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.source,self.candidate))))
        for bad in (self.candidate,self.source[:-1],bytes(len(self.source))):
            with self.assertRaises(ValueError):patch.build(bad)

    def test_rounding_edges_random_and_live_registers(self):
        rng=random.Random(0x1FCA8)
        values=set(range(-1024,1025))
        values.update(range(-(1<<31),-(1<<31)+256))
        values.update(range((1<<31)-256,1<<31))
        values.update(rng.getrandbits(32) for _ in range(20000))
        # Allowed differences are caller-dead a0/a1/a2,v1,ra and HI/LO.
        # Every other GPR must match at the immediately following instruction.
        live=[0,1,2,*range(7,31)]
        for pc,(constant,k) in patch.SITES.items():
            for b in values:
                old=replay(self.source,pc,b);new=replay(self.candidate,pc,b)
                expected=((signed(b&MASK)*constant+(1<<11))>>12)&MASK
                self.assertEqual(old[0][2],expected,(pc,b,'original'))
                self.assertEqual(new[0][2],expected,(pc,b,'candidate'))
                self.assertEqual([old[0][r] for r in live],[new[0][r] for r in live])
                self.assertEqual((old[3],new[3]),(17,4))
        print({'cases_per_site':len(values),'sites':3,'dispatches_original':17,'dispatches_candidate':4,
               'scope':'Window arithmetic/live-GPR comparison, not guest-cycle or game benchmark'})


if __name__=='__main__':unittest.main()
