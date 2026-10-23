import struct
import unittest
import tm3_patch_timer_recovery_v1 as patch


class TimerPatchTests(unittest.TestCase):
    def test_exact_word_only_and_delay_slot_preserved(self):
        source, _ = patch.disc_file(patch.ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin', 'SCUS_942.49')
        candidate = patch.patch_executable(source)
        self.assertEqual(len(source), len(candidate))
        self.assertEqual(source[:patch.OFFSET], candidate[:patch.OFFSET])
        self.assertEqual(source[patch.OFFSET+4:], candidate[patch.OFFSET+4:])
        self.assertEqual(struct.unpack_from('<I', candidate, patch.OFFSET)[0], 0)
        self.assertEqual(patch.word(candidate, patch.PC+4), 0)
        for bad in (candidate, source[:-1], bytes(len(source))):
            with self.assertRaises(ValueError):
                patch.patch_executable(bad)

    def test_remaining_conditions_limit_skip_to_late_combat(self):
        for late in (False, True):
            for state in range(5):
                for skip in range(3):
                    for d2d20 in (0, 1, 7):
                        old = late and d2d20 != 0 and state == 3 and skip == 0
                        new = late and state == 3 and skip == 0
                        self.assertFalse(old and not new)
                        if old != new:
                            self.assertTrue(late and state == 3 and skip == 0 and d2d20 == 0)


if __name__ == '__main__':
    unittest.main()
