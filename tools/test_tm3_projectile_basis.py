import random
import struct
import unittest

import tm3_patch_projectile_basis_v1 as patch
from replay_tm3_projectile_basis import replay
from tm3_patch_path_stamp_v1 import replay_ips


class ProjectileBasisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = patch.SOURCE.read_bytes()
        cls.candidate, cls.ips, cls.meta = patch.build(cls.source)

    def test_exact_scope_and_ips(self):
        self.assertEqual(replay_ips(self.source,self.ips), self.candidate)
        self.assertEqual(len(self.source), len(self.candidate))
        self.assertEqual(self.source[:patch.at(patch.START)], self.candidate[:patch.at(patch.START)])
        self.assertEqual(self.source[patch.at(patch.END):], self.candidate[patch.at(patch.END):])

    def test_reject_wrong_source(self):
        altered = bytearray(self.source); altered[-1] ^= 1
        with self.assertRaises(ValueError): patch.build(altered)
        with self.assertRaises(ValueError): patch.build(self.candidate)

    def test_captured_forward_old_depends_on_heap_new_does_not(self):
        forward = (0,-2585,-3180)
        poison = [(111,222,333),(-400,500,-600)]
        old = [replay(self.source,forward,p)['right'] for p in poison]
        new = [replay(self.candidate,forward,p)['right'] for p in poison]
        self.assertEqual(old,poison)
        self.assertEqual(new,[(-3180,0,0)]*2)

    def test_z_zero_and_vertical_cases(self):
        for forward, expected in [((3000,0,0),(0,0,-3000)), ((-3000,0,0),(0,0,3000)),
                                  ((0,4096,0),(4096,0,0)), ((0,-4096,0),(4096,0,0)),
                                  ((0,0,0),(4096,0,0))]:
            for poison in ((111,222,333),(-400,500,-600)):
                actual = replay(self.candidate,forward,poison)
                self.assertEqual(actual['right'],expected)
                self.assertEqual(actual['forward'],forward)
                self.assertEqual(actual['args'],(actual['object']+0x74,2,0))
                self.assertEqual(set(actual['writes']),{actual['object']+o for o in (0x74,0x7a,0x80)})

    def test_ordinary_case_preserves_input_to_existing_normalizer(self):
        rng = random.Random(3186)
        for _ in range(512):
            forward = (rng.choice((-1,1))*rng.randint(1,4096),rng.randint(-4096,4096),
                       rng.choice((-1,1))*rng.randint(1,4096))
            poison = tuple(rng.randint(-32768,32767) for _ in range(3))
            old,new = (replay(b,forward,poison) for b in (self.source,self.candidate))
            for key in ('right','forward','args'):
                self.assertEqual(old[key],new[key])

    def test_heap_independence_for_all_axis_cases(self):
        rng = random.Random(3150)
        for forward in ((0,-2585,-3180),(0,0,4096),(4096,0,0),(0,4096,0)):
            expected = None
            for _ in range(64):
                poison = tuple(rng.randint(-32768,32767) for _ in range(3))
                actual = replay(self.candidate,forward,poison)['right']
                expected = actual if expected is None else expected
                self.assertEqual(actual,expected)
                self.assertEqual(sum(a*b for a,b in zip(actual,forward)),0)

    def test_orthonormalizer_reads_lateral_column_before_writing(self):
        # Static premise in the exact guarded source, not a guessed function name.
        for pc, ins in {0x80015198:0x86220000, 0x8001519C:0x86230006,
                        0x800151A0:0x8625000C, 0x800151CC:0x0C00791C}.items():
            self.assertEqual(patch.word(self.source,pc),ins)

    def test_replay_fails_on_unknown_instruction(self):
        invalid=bytearray(self.candidate)
        struct.pack_into('<I',invalid,patch.at(patch.START),0xFFFFFFFF)
        with self.assertRaises(ValueError): replay(invalid,(0,1,2),(3,4,5))


if __name__ == '__main__': unittest.main()
