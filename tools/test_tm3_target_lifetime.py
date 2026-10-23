import random
import unittest

import tm3_patch_target_lifetime_v1 as patch
from tm3_patch_path_stamp_v1 import replay_ips
from replay_tm3_target_lifetime import cleanup,valid_target,SP,GP,capture_replay


class LifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=patch.SOURCE.read_bytes()
        cls.candidate,cls.ips,cls.meta=patch.build(cls.original)

    def test_empty_list_and_tail_call_preserve_registers(self):
        machine,mem,regs=cleanup(self.candidate,0x801675D8,[])
        expected=list(regs); expected[4]=regs[17]; expected[31]=patch.HOOK+8
        self.assertEqual(machine.regs,expected)
        self.assertEqual(machine.pc,patch.ORIGINAL_CALLEE)
        self.assertIsNone(machine.pending)

    def test_only_matching_type8_targets_are_cleared(self):
        dying=0x801675D8
        nodes=[(0x80110000,0,dying),(0x80120000,8,dying),(0x80130000,0x16,dying),
               (0x80140000,8,0x80162BF8),(0x80150000,8,0),(0x80160000,8,dying)]
        machine,mem,regs=cleanup(self.candidate,dying,nodes)
        targets={h+0xd4 for h,t,p in nodes if t==8 and p==dying}
        for addr,value in machine.memory.items():
            if SP-16<=addr<SP: continue
            self.assertEqual(value,0 if addr in targets else mem[addr])
        self.assertEqual(set(machine.writes),targets|{SP-16,SP-12,SP-8})
        self.assertEqual(machine.regs[8:11],regs[8:11])
        self.assertEqual(machine.regs[29],SP)
        self.assertIsNone(machine.pending)

    def test_unrelated_objects_are_not_read_beyond_header(self):
        machine,_,_=cleanup(self.candidate,0x801675D8,[(0x80110000,3,0),(0x80120000,0x16,0)])
        self.assertNotIn(0x801100d4,machine.reads)
        self.assertNotIn(0x801200d4,machine.reads)

    def test_multiple_deaths_and_live_target_preserved(self):
        nodes=[(0x80110000,8,0x80170000),(0x80120000,8,0x80180000),(0x80130000,8,0x80190000)]
        first,_,_=cleanup(self.candidate,0x80170000,nodes)
        nextnodes=[(h,t,first.memory[h+0xd4]) for h,t,_ in nodes]
        second,_,_=cleanup(self.candidate,0x80180000,nextnodes)
        self.assertEqual([second.memory[h+0xd4] for h,_,_ in nodes],[0,0,0x80190000])

    def test_original_address_reuse_bug_is_removed(self):
        dying=0x801675D8; nodes=[(0x80110000,8,dying)]
        old,_,_=cleanup(self.original,dying,nodes)
        new,_,_=cleanup(self.candidate,dying,nodes)
        tables=([0x80162bf8,dying],[0x80162bf8,0x80167588])
        self.assertEqual([valid_target(self.original,old.memory[0x801100d4],t) for t in tables],[1,0])
        self.assertEqual([valid_target(self.candidate,new.memory[0x801100d4],t) for t in tables],[0,0])

    def test_random_order_and_large_lists(self):
        rng=random.Random(3368); dying=0x801675D8
        nodes=[(0x80100000+i*0x200,rng.choice([0,3,8,8,0x16]),rng.choice([dying,0,0x80190000])) for i in range(512)]
        rng.shuffle(nodes)
        machine,_,_=cleanup(self.candidate,dying,nodes)
        for head,kind,target in nodes:
            if kind==8: self.assertEqual(machine.memory[head+0xd4],0 if target==dying else target)

    def test_capture_reproduces_both_sides(self):
        result=capture_replay()
        self.assertEqual(set(result['sides']),{'Oscar','Sofia'})

    def test_exact_patch_scope_and_ips(self):
        self.assertEqual(replay_ips(self.original,self.ips),self.candidate)
        allowed=set(range(patch.at(patch.HOOK),patch.at(patch.HOOK)+4))|set(range(patch.at(patch.CAVE),patch.at(patch.CAVE)+len(patch.helper())))
        self.assertEqual(len(self.original),len(self.candidate))
        self.assertTrue({i for i,(a,b) in enumerate(zip(self.original,self.candidate)) if a!=b}<=allowed)
        for lo,hi in [(0x8003A0F0,0x8003A120),(0x8003AB78,0x8003ABD0),(0x80047728,0x80047C80),
                      (0x8002D8A8,0x8002D8F0),(0x8002ED64,0x8002ED80)]:
            self.assertEqual(self.original[patch.at(lo):patch.at(hi)],self.candidate[patch.at(lo):patch.at(hi)])

    def test_reject_modified_source(self):
        altered=bytearray(self.original); altered[-1]^=1
        with self.assertRaises(ValueError): patch.build(altered)
        with self.assertRaises(ValueError): patch.build(self.candidate)


if __name__=='__main__': unittest.main()
