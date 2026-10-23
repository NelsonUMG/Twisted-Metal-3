#!/usr/bin/env python3
"""Static SCUS/IPS checks plus a small visited-generation counterexample.

The model tests prove only the stamp-allocation property. They do not reproduce
TM3's pathfinding algorithm, MIPS timing, or a network gameplay session.
"""
from __future__ import annotations

import itertools
import unittest

import tm3_patch_path_stamp_v1 as candidate


class StampModel:
    def __init__(self, shared: bool):
        self.shared = shared
        self.counters = {"destination": 0, "random": 0}
        self.visited = {}

    def begin(self, kind: str) -> int:
        key = "destination" if self.shared else kind
        self.counters[key] = (self.counters[key] + 1) & 0xFFFF
        return self.counters[key]

    def visit(self, node: str, generation: int) -> bool:
        if self.visited.get(node, 0) == generation:
            return False
        self.visited[node] = generation
        return True


class GenerationRegression(unittest.TestCase):
    def test_separate_counters_reuse_tag_from_other_search(self):
        old = StampModel(shared=False)
        self.assertTrue(old.visit("candidate", old.begin("destination")))
        self.assertFalse(old.visit("candidate", old.begin("random")))

    def test_shared_counter_does_not_skip_previously_visited_node(self):
        new = StampModel(shared=True)
        first = new.begin("destination")
        self.assertTrue(new.visit("candidate", first))
        second = new.begin("random")
        self.assertEqual((first, second), (1, 2))
        self.assertTrue(new.visit("candidate", second))
        self.assertFalse(new.visit("candidate", second))  # Same-search guard survives.

    def test_all_small_serial_interleavings_have_unique_shared_generations(self):
        for sequence in itertools.product(("destination", "random"), repeat=8):
            model = StampModel(shared=True)
            stamps = [model.begin(kind) for kind in sequence]
            self.assertEqual(stamps, list(range(1, 9)))

    def test_different_prior_searches_can_change_later_old_visited_decision(self):
        # Same random call count, different previous destination search footprint.
        outcomes = {}
        for shared in (False, True):
            decisions = []
            for touched in ("candidate", "unrelated"):
                model = StampModel(shared=shared)
                model.visit(touched, model.begin("destination"))
                decisions.append(model.visit("candidate", model.begin("random")))
            outcomes[shared] = decisions
        self.assertEqual(outcomes[False], [False, True])
        self.assertEqual(outcomes[True], [True, True])

    def test_wrap_remains_a_real_limitation(self):
        model = StampModel(shared=True)
        model.visit("old_node", model.begin("destination"))  # Stamp 1.
        for _ in range(65535):
            model.begin("random")
        self.assertEqual(model.begin("destination"), 1)
        self.assertFalse(model.visit("old_node", 1))


class ExactExecutableRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = candidate.SOURCE.read_bytes()
        cls.patched, cls.patch, cls.metadata = candidate.build(cls.source)

    def test_exactly_four_low_immediate_bytes_change(self):
        self.assertEqual(len(self.source), len(self.patched))
        changed = [i for i, pair in enumerate(zip(self.source, self.patched)) if pair[0] != pair[1]]
        self.assertEqual(changed, [candidate.offset(pc) for pc in candidate.PATCH_WORDS])
        self.assertTrue(all(self.source[i] == 0x1E and self.patched[i] == 0x1C for i in changed))

    def test_destination_counter_and_shared_tag_operands_stay_intact(self):
        for pc, expected in candidate.CONTEXT_WORDS.items():
            self.assertEqual(candidate.word(self.patched, pc), expected)
        refs = candidate.counter_refs(self.patched, 0x80016EA8, 0x8001746C)
        self.assertEqual(refs, {pc: new for pc, (_, new) in candidate.PATCH_WORDS.items()})

    def test_ips_replay_reproduces_entire_candidate(self):
        self.assertEqual(len(self.patch), 32)
        self.assertEqual(candidate.replay_ips(self.source, self.patch), self.patched)

    def test_wrong_source_is_rejected_even_outside_patch_sites(self):
        changed = bytearray(self.source)
        changed[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "exact v12 control"):
            candidate.build(bytes(changed))

    def test_reapplying_to_candidate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact v12 control"):
            candidate.build(self.patched)

    def test_truncated_ips_is_rejected(self):
        with self.assertRaises(ValueError):
            candidate.replay_ips(self.source, self.patch[:-1])


if __name__ == "__main__":
    unittest.main()
