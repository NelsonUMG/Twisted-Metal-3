"""Bounded real-instruction replay, not a full game/CD/GPU acceptance test."""
import itertools
import unittest

import tm3_patch_menu_reload_v1 as patch
from analyze_tm3_lifecycle import read_trace, describe
from replay_tm3_target_lifetime import Mips
from tm3_patch_path_stamp_v1 import replay_ips

FLAG = 0x800D2D4C


def gate(blob, previous, destination, ui, variant=1, map_reload=0):
    regs = [0]+[0x76540000+n for n in range(1, 32)]
    regs[21], regs[22] = destination, previous
    mem = {FLAG: 0xDEADBEEF, 0x800D2D48: ui,
           0x800D2D54: variant, 0x800D2DB0: map_reload}
    return Mips(blob, 0x800451B4, mem, regs).run(0x8004521C, limit=100)


class MenuReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = patch.SOURCE.read_bytes()
        cls.candidate, cls.ips, cls.meta = patch.build(cls.source)

    def test_exact_instruction_and_ips_scope(self):
        self.assertEqual(replay_ips(self.source, self.ips), self.candidate)
        self.assertEqual(len(self.source), len(self.candidate))
        self.assertEqual(self.meta['changed_bytes'], 3)
        self.assertEqual(self.source[:patch.at(patch.HOOK)], self.candidate[:patch.at(patch.HOOK)])
        self.assertEqual(self.source[patch.at(patch.HOOK)+4:], self.candidate[patch.at(patch.HOOK)+4:])

    def test_refuse_wrong_lineage_or_double_patch(self):
        for source in (self.source[:-1], self.candidate, bytes(len(self.source))):
            with self.assertRaises(ValueError):
                patch.build(source)

    def test_full_gate_all_configurations_and_original_map_predicate(self):
        # Executes actual 44898 too, with real MIPS branch/load delays.
        for prev, dest, ui, variant, reload in itertools.product(range(5), range(4), range(3), range(3), range(2)):
            with self.subTest(previous=prev, destination=dest, ui=ui, variant=variant, reload=reload):
                old = gate(self.source, prev, dest, ui, variant, reload)
                new = gate(self.candidate, prev, dest, ui, variant, reload)
                map_needed = variant != 1 or reload != 0
                expected = prev == 0 or ui == 2 or (dest == 3 and (prev in (1, 2) or map_needed)) or (dest == 1 and prev == 1)
                self.assertEqual(old.memory[FLAG], int(expected))
                self.assertEqual(new.memory[FLAG], int(expected or dest == 1))
                self.assertEqual(new.writes, [FLAG])
                self.assertIsNone(new.pending)
                if dest != 1 or expected:
                    self.assertEqual(old.regs, new.regs)
                    self.assertEqual(old.memory, new.memory)
                else:
                    # Only the two scratch regs needed to store 1 may differ.
                    self.assertEqual(old.regs[:2]+old.regs[4:], new.regs[:2]+new.regs[4:])

    def test_caller_takes_reload_path_instead_of_skipping_it(self):
        for blob, stop in ((self.source, 0x8003A484), (self.candidate, 0x8003A3E4)):
            flag = gate(blob, 3, 1, 1).memory[FLAG]
            regs = [0]*32; regs[20] = 0x800D2CB0
            m = Mips(blob, 0x8003A3D4, {FLAG: flag}, regs).run(stop, limit=5)
            self.assertEqual(m.pcs, [0x8003A3D4, 0x8003A3D8, 0x8003A3DC, 0x8003A3E0])
            self.assertEqual(m.regs[4], 0)  # delay slot honored in both paths

    def test_real_quit_and_tournament_captures_match_the_fixed_gate(self):
        runs = ('LifecycleTraceV1_20261011_175146_251_f240fdd5',
                'VideoPresentV1_20261012_034754_214_6f9bda87')
        for run, side in itertools.product(runs, ('Oscar', 'Sofia')):
            rows, _ = read_trace(patch.ROOT/'diagnostics/link_pause_v1/runs'/run/f'{side}.lifecycle.bin')
            returns = [i for i, r in enumerate(rows) if r[1] == 0x80044E5C and
                       describe(r)['globals']['current_state'] == 3 and
                       describe(r)['globals']['requested_state'] == 4]
            self.assertTrue(returns, (run, side))
            tail = rows[returns[-1]:]
            self.assertNotIn(0x80048CA4, [r[1] for r in tail])
            constructor = [describe(r) for r in tail if r[1] == 0x80017CD4][-1]
            state = constructor['globals']
            self.assertEqual((state['current_state'], state['role'], state['load_menu']), (1, 0, 0))
            self.assertEqual(state['sync_error'], 0)
            self.assertIn(tail[-1][1], (0xBFC05F5C, 0xBFC05F60))
            self.assertEqual(gate(self.source, 3, 1, state['ui_state']).memory[FLAG], 0)
            self.assertEqual(gate(self.candidate, 3, 1, state['ui_state']).memory[FLAG], 1)

    def test_original_lookup_and_previous_fixes_not_modified(self):
        for start, end in ((0x80026C40, 0x80026C9C), (0x80048CA4, 0x80048F00),
                           (0x80018D44, 0x80018D4C), (0x80047C80, 0x80047CEC),
                           (0x8002D8A8, 0x8002D8E8), (0x8003AA00, 0x8003CD00),
                           (0x800518C8, 0x80052000)):
            self.assertEqual(self.source[patch.at(start):patch.at(end)],
                             self.candidate[patch.at(start):patch.at(end)])


if __name__ == '__main__':
    unittest.main()
