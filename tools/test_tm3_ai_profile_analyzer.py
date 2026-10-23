#!/usr/bin/env python3
"""Prueba sintética del parser/reportador TM3 AI Profile V2."""

from __future__ import annotations

import csv
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze_tm3_ai_profile as analyzer


FIELDS = (
    "event_seq,target_id,target,phase,pc,ra,sp,gp,timestamp,instruction,"
    "duration_instructions,duration_timestamp,boundary_ordinal,vehicle_order,"
    "vehicle,table_index,f50,driver_type,callback,d06,d08,gp_e8,seed,registered,"
    "cpu_count,human_count,net_humans,f58,f5c,f60,f64,f68,f6c,f70,f74,f78,f7c,"
    "f80,f9c,scope_flags,a0,a1,a2,a3,v0,v1,d3a,path_generation,d3e,d42,d43,"
    "d44,d48,e84,e86,graph_base,node0,node1,node2,node3,node4,node5,node6"
).split(",")


def event(sequence: int, target_id: int, target: str, phase: str,
          instruction: int, duration: int = 0) -> dict[str, str | int]:
    row: dict[str, str | int] = {field: 0 for field in FIELDS}
    row.update({
        "event_seq": sequence,
        "target_id": target_id,
        "target": target,
        "phase": phase,
        "pc": "0x8001A40C" if target == "cpu_callback" else "0x80018338",
        "ra": "0x80018350",
        "sp": "0x801FFF00",
        "gp": "0x800894C0",
        "timestamp": instruction * 2,
        "instruction": instruction,
        "duration_instructions": duration,
        "duration_timestamp": duration * 2,
        "boundary_ordinal": 1,
        "vehicle_order": 1,
        "vehicle": "0x800C0000" if target != "boundary" else "0x00000000",
        "table_index": 2 if target != "boundary" else 0xFFFFFFFF,
        "f50": 2 if target != "boundary" else 0xFFFFFFFF,
        "driver_type": 2 if target != "boundary" else 0xFFFFFFFF,
        "callback": "0x8001A40C" if target != "boundary" else "0x00000000",
        "seed": "0x12345678",
        "registered": 8,
        "cpu_count": 6,
        "human_count": 2,
        "net_humans": 2,
        "scope_flags": "0x00000000",
        "a0": "0x800C0E84",
        "a1": "0x0000002A",
        "a2": "0x0000000F",
        "a3": "0x80089D18",
        "v0": "0x00000000",
        "v1": "0x00000000",
        "d3a": 42,
        "path_generation": 7,
        "d3e": 41,
        "d42": 0,
        "d43": 0,
        "d44": "0x00000000",
        "d48": "0x00000000",
        "e84": 41,
        "e86": 42,
        "graph_base": "0x80100000",
    })
    for index in range(7):
        row[f"node{index}"] = f"0x{index:08X}"
    for field in analyzer.STATE_FIELDS:
        row[field] = "0x00000000"
    return row


class AnalyzerTest(unittest.TestCase):
    def test_complete_capture_and_hotspot(self) -> None:
        rows = [
            event(1, 1, "boundary", "enter", 1),
            event(2, 5, "vehicle_update", "enter", 10),
            event(3, 7, "cpu_callback", "enter", 20),
            event(4, 7, "cpu_callback", "exit", 120, 100),
            event(5, 5, "vehicle_update", "exit", 210, 200),
        ]
        rows[3]["f5c"] = "0x00000001"
        rows[4]["f5c"] = "0x00000001"

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            csv_path = directory / "capture.events.csv"
            hist_path = directory / "capture.hist.bin"
            meta_path = directory / "capture.meta.txt"
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            words_per_category = (analyzer.PC_END - analyzer.PC_BEGIN) // 4
            histogram = bytearray(words_per_category * len(analyzer.HIST_CATEGORIES) * 4)
            cpu_pc_index = (0x8001A40C - analyzer.PC_BEGIN) // 4
            struct.pack_into("<I", histogram, (words_per_category + cpu_pc_index) * 4, 100)
            hist_path.write_bytes(histogram)
            meta_path.write_text("dropped_events=0\n", encoding="utf-8")

            parsed_capture = analyzer.read_events(csv_path)
            parsed = parsed_capture.rows
            self.assertEqual(parsed[0]["path_generation"], 7)
            self.assertEqual(parsed[0]["node6"], 6)
            integrity = analyzer.capture_integrity(
                parsed, analyzer.read_meta(meta_path), parsed_capture.malformed_rows
            )
            self.assertTrue(any("íntegra" in line for line in integrity))
            validation, issues = analyzer.validate_state(parsed)
            self.assertEqual(sum(issues.values()), 0, validation)
            self.assertTrue(any("1/1/1" in line for line in analyzer.order_analysis(parsed)))
            self.assertTrue(any("`f5c`" in line for line in analyzer.state_delta_analysis(parsed)))

            labels = analyzer.read_pc_labels(
                Path(__file__).resolve().parents[1] / "diagnostics/tm3_profile_pcmap_v20.csv"
            )
            hotspot = analyzer.histogram_analysis(analyzer.read_histogram(hist_path), labels)
            self.assertTrue(any("FUN_8001a40c" in line for line in hotspot))

            report_path = directory / "report.md"
            with mock.patch.object(sys, "argv", [
                "analyze_tm3_ai_profile.py",
                "--events", str(csv_path),
                "--histogram", str(hist_path),
                "--pc-map", str(Path(__file__).resolve().parents[1] /
                                  "diagnostics/tm3_profile_pcmap_v20.csv"),
                "--output", str(report_path),
            ]):
                self.assertEqual(analyzer.main(), 0)
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Captura íntegra", report)
            self.assertIn("FUN_8001a40c", report)


if __name__ == "__main__":
    unittest.main()
