"""Static and branch/load-delay-aware tests, not a full pause-menu replay."""
import unittest
import tm3_patch_link_pause_v1 as patch


def guard(blob,success,local,remote):
    regs=[0]*32
    regs[2]=success
    regs[20]=0x800D2CB0
    regs[29]=0x80100000
    mem={regs[20]+0x8c:local,regs[29]+0xa8:remote}
    pc,npc,pending=0x8003AA98,0x8003AA9C,None
    for _ in range(100):
        if pc in (0x8003AB30,0x8003AB78): return pc,regs[2]
        ins=patch.word(blob,pc)
        op,rs,rt=ins>>26,(ins>>21)&31,(ins>>16)&31
        imm=ins&0xffff
        if imm&0x8000:imm-=0x10000
        target,load=None,None
        if ins==0:pass
        elif op==0x23:load=(rt,mem[regs[rs]+imm])
        elif op in (4,5):
            taken=(regs[rs]==regs[rt]) if op==4 else (regs[rs]!=regs[rt])
            if taken:target=pc+4+4*imm
        else:raise AssertionError(f'unexpected guard opcode {ins:08X}')
        if pending:regs[pending[0]]=pending[1]
        pending=load
        pc,npc=npc,target if target is not None else npc+4
    raise AssertionError('guard did not terminate')


class PauseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=patch.SOURCE.read_bytes()
        cls.result,cls.ips,cls.meta=patch.build(cls.source)

    def test_original_batch_ignores_pause(self):
        for local,remote in ((1,0),(0,1),(1,1)):
            self.assertEqual(guard(self.source,1,local,remote)[0],0x8003AB78)

    def test_normal_success_preserved(self):
        self.assertEqual(guard(self.result,1,0,0),(0x8003AB78,1))

    def test_each_pause_direction_and_both(self):
        for local,remote in ((1,0),(0,1),(1,1),(4,0),(0,4),(0xffffffff,0)):
            self.assertEqual(guard(self.result,1,local,remote)[0],0x8003AB30)

    def test_failure_dispatch_preserved(self):
        for local,remote in ((0,0),(1,0),(0,1),(1,1)):
            self.assertEqual(guard(self.result,0,local,remote)[0],0x8003AB30)

    def test_retry_targets_include_batch_call(self):
        ins=patch.word(self.result,0x8003AB50)
        signed=(ins&0xffff)-0x10000
        self.assertEqual(0x8003AB54+4*signed,0x8003AA90)
        for pc in (0x8003AB68,0x8003AB70):
            ins=patch.word(self.result,pc)
            self.assertEqual(0x80000000|((ins&0x3ffffff)<<2),0x8003AA90)

    def test_ips_exact(self):
        self.assertEqual(patch.stamp.replay_ips(self.source,self.ips),self.result)

    def test_reject_wrong_input(self):
        wrong=bytearray(self.source);wrong[0x800]^=1
        with self.assertRaises(ValueError):patch.build(bytes(wrong))


if __name__=='__main__':unittest.main()
