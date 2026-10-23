"""Regression tests for protocol alignment, not process-global hook counts."""

from pathlib import Path
import tempfile
import unittest

import analyze_tm3_producer_cause as subject


def record(kind, visit, *, pc=0x8001A360, seed=0x1234, clock=3,
           value=0x2D, offset=0xD3A, generation=6, node=0x2D, **words):
    r = [0] * 64
    r[0], r[1], r[3] = kind, pc, visit
    r[5], r[6], r[7] = 0x001815F2, 2, value
    r[8], r[10], r[11], r[12] = 0x801808B8, seed, clock, generation
    r[20], r[22], r[23] = 0x1678A4, offset, 0xFFFFFFFF
    r[45:49] = [0x8018173C, node, 15, 0x800D2CAC]
    for key, val in words.items():
        r[int(key.removeprefix("w"))] = val
    return tuple(r)


def tx(ordinal, clock, seed):
    return (f"TX seq={ordinal} ord={ordinal} call=8003AA98 sizes=48/48 mode=BATCH "
            f"local-time=0x{clock:X} local-random=0x{seed:X}")


def fixture(side):
    # Raw visit counts differ by peer and never equal protocol ordinals 1..5.
    shift = 20 if side == "Oscar" else 70
    end_seed = 0x1111 if side == "Oscar" else 0x2222
    pregame = record(1, 0, value=0x22 if side == "Oscar" else 0x05)
    rows = [pregame]
    logs = []
    for n in range(1, 6):
        seed = 0x1000 + n if n < 4 else 0x1234 if n == 4 else end_seed
        rows.append(record(3, shift + n, pc=0x8003AA98, seed=seed, clock=n - 1))
        logs.append(tx(n, n - 1, seed))
        if n == 4:
            rows.append(record(1, shift + n))
            rows.append(record(2, shift + n, pc=0x80016EA8, offset=0xFFFFFFFF))
    logs.append("RX_RESPONSE seq=5 ord=5 sync=RANDOM_MISMATCH")
    return rows, subject.network_index(logs)


class ProtocolAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.left, self.net_left = fixture("Oscar")
        self.right, self.net_right = fixture("Sofia")

    def analyze(self):
        return subject.analyze_records(self.left, self.right, self.net_left, self.net_right)

    def test_excludes_demo_differences_and_aligns_unequal_visit_counters(self):
        result = self.analyze()
        self.assertEqual(result["comparison_protocol_interval"], 4)
        self.assertEqual(result["network_first_mismatch"], {"Oscar": 5, "Sofia": 5})
        self.assertIsNone(result["first_store_difference_in_interval"])
        self.assertIsNone(result["first_path_selector_writer_difference_in_interval"])
        self.assertIsNone(result["first_path_entry_difference_in_interval"])
        self.assertTrue(result["all_initial_network_states_equal"])
        self.assertTrue(result["initial_network_ordinals_complete"])
        self.assertTrue(result["pregame_excluded"])
        self.assertEqual(result["excluded_records_before_first_aligned_boundary"], {"Oscar": 1, "Sofia": 1})

    def test_reports_real_interval_store_difference_not_demo_writer(self):
        self.right[-3] = record(1, 74, pc=0x80017284, value=9)
        result = self.analyze()["first_store_difference_in_interval"]
        self.assertEqual(result["stream_index_in_interval"], 0)
        self.assertEqual(result["sofia"]["pc"], "0x80017284")
        self.assertEqual(result["sofia"]["protocol_interval"], 4)
        self.assertEqual(result["sofia"]["boundary_visit_count"], 74)
        self.assertNotIn("ordinal", result["sofia"])

    def test_path_arguments_are_compared_even_with_identical_vehicle_state(self):
        self.right[-2] = record(2, 74, pc=0x80016EA8, node=0x32, offset=0xFFFFFFFF)
        result = self.analyze()["first_path_entry_difference_in_interval"]
        self.assertEqual(result["oscar"]["start_node_signed16"], 0x2D)
        self.assertEqual(result["sofia"]["start_node_signed16"], 0x32)
        self.assertEqual(result["sofia"]["arguments"]["a3"], "0x800D2CAC")
        self.assertEqual(result["sofia"]["actual_graph_base_cached"], "0x801678A4")

    def test_generation_and_node_tag_evidence_is_explicit(self):
        self.right[-2] = record(2, 74, pc=0x80016EA8, generation=8,
                                offset=0xFFFFFFFF, w53=0x00060000)
        result = self.analyze()["first_path_entry_difference_in_interval"]["sofia"]
        self.assertEqual(result["generation_gp_1e_pre_instruction"], 8)
        self.assertEqual(result["node_generation_tag_at_0x12"], 6)
        self.assertIsNone(result["generation_gp_1c"])
        self.assertEqual(self.analyze()["capture_limitations"]["graph_store_nodes_covered"], 16)

    def test_requires_both_aligned_endpoints_and_never_uses_raw_ordinal_fallback(self):
        self.right[-1] = record(3, 5, seed=0xDEAD, clock=4)
        result = self.analyze()
        self.assertIn("Missing uniquely aligned", result["comparison_status"])
        self.assertNotIn("first_store_difference_in_interval", result)

    def test_ambiguous_network_state_does_not_map_boundary(self):
        self.net_right = subject.network_index([
            tx(4, 3, 0x1234), tx(99, 3, 0x1234), tx(5, 4, 0x2222),
            "RX ord=5 sync=RANDOM_MISMATCH",
        ])
        result = self.analyze()
        self.assertEqual(result["alignment"]["Sofia"]["ambiguous_boundaries"], 1)
        self.assertNotIn("first_store_difference_in_interval", result)

    def test_repeated_preexecution_boundary_uses_last_visit(self):
        self.left.insert(-3, record(3, 55, pc=0x8003AA98, seed=0x1234, clock=3))
        result = self.analyze()
        self.assertEqual(result["alignment"]["Oscar"]["repeated_preexecution_boundary_visits"], 1)
        self.assertIsNone(result["first_store_difference_in_interval"])

    def test_unmapped_boundary_inside_interval_prevents_causal_comparison(self):
        self.left.insert(-2, record(3, 56, pc=0x8003AA98, seed=0xDEAD, clock=3))
        result = self.analyze()
        self.assertIn("Unresolved intermediate", result["comparison_status"])
        self.assertNotIn("first_store_difference_in_interval", result)

    def test_no_mismatch_does_not_invent_one_from_last_visit(self):
        self.net_left = self.net_right = subject.network_index([tx(1, 0, 0x1001)])
        result = self.analyze()
        self.assertIsNone(result["first_protocol_state_difference"])
        self.assertNotIn("comparison_protocol_interval", result)

    def test_conflicting_reused_protocol_ordinal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting BATCH TX"):
            subject.network_index([tx(1, 0, 1), tx(1, 0, 2)])

    def test_direct_handshake_ordinals_do_not_count_as_batch_states(self):
        states, ordinals, mismatch = subject.network_index([
            "TX seq=1 ord=1 call=80047EA0 sizes=4/4 mode=DIRECT word=0", tx(4, 3, 0x1234),
        ])
        self.assertEqual(ordinals, {4: (3, 0x1234)})
        self.assertEqual(states, {(3, 0x1234): {4}})
        self.assertIsNone(mismatch)

    def test_reader_preserves_complete_records_and_rejects_wrong_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.bin"
            path.write_bytes(subject.HEADER.pack(subject.MAGIC, 1, 256, 10)
                             + subject.RECORD.pack(*self.left[0]) + b"partial")
            records, cap = subject.read_trace(path)
            self.assertEqual(records, [self.left[0]])
            self.assertEqual(cap, 10)
            path.write_bytes(subject.HEADER.pack(0x31435054, 1, 256, 10))
            with self.assertRaisesRegex(ValueError, "unsupported header"):
                subject.read_trace(path)


if __name__ == "__main__":
    unittest.main()
