"""Compare PRC1 observations inside a verified NetBridge BATCH interval.

PRC1 word 3 counts pre-execution visits to 0x8003AA98. It is not a protocol
ordinal. Only a unique per-peer (TIME, seed) match to a BATCH TX establishes
that relationship. Pregame/demo observations are never causal comparisons.
"""

from __future__ import annotations

import argparse
from itertools import zip_longest
import json
import re
import struct
from pathlib import Path


HEADER = struct.Struct("<4I")
RECORD = struct.Struct("<64I")
MAGIC = 0x31435250
KINDS = {1: "store", 2: "path_entry", 3: "boundary", 4: "control_entry"}
TX_PATTERN = re.compile(
    r"^TX seq=\d+ ord=(\d+) call=8003AA98 .*"
    r"local-time=0x([0-9A-Fa-f]+) local-random=0x([0-9A-Fa-f]+)"
)
MISMATCH_PATTERN = re.compile(r"\bord=(\d+).*sync=(?:RANDOM_MISMATCH|TIME_MISMATCH)")


def read_trace(path: Path) -> tuple[list[tuple[int, ...]], int]:
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise ValueError(f"{path}: incomplete PRC1 header")
    magic, version, record_bytes, cap = HEADER.unpack_from(data)
    if (magic, version, record_bytes) != (MAGIC, 1, RECORD.size):
        raise ValueError(f"{path}: unsupported header {magic:08X}/{version}/{record_bytes}")
    payload = data[HEADER.size:]
    count = len(payload) // RECORD.size
    if count > cap:
        raise ValueError(f"{path}: records exceed declared cap")
    # A live file may end in a partial record. Compare completed records only.
    return [RECORD.unpack_from(payload, index * RECORD.size) for index in range(count)], cap


def network_index(lines) -> tuple[dict[tuple[int, int], set[int]], dict[int, tuple[int, int]], int | None]:
    by_state, by_ordinal = {}, {}
    mismatch = None
    for line in lines:
        match = TX_PATTERN.search(line)
        if match:
            ordinal = int(match[1])
            state = (int(match[2], 16), int(match[3], 16))
            if ordinal in by_ordinal and by_ordinal[ordinal] != state:
                raise ValueError(f"Conflicting BATCH TX states for ordinal {ordinal}; split sessions first")
            by_state.setdefault(state, set()).add(ordinal)
            by_ordinal[ordinal] = state
        match = MISMATCH_PATTERN.search(line)
        if match and mismatch is None:
            mismatch = int(match[1])
    return by_state, by_ordinal, mismatch


def align_boundaries(records, network_states):
    boundaries, visit_to_protocol = {}, {}
    unmapped = ambiguous = repeated = 0
    for index, record in enumerate(records):
        if record[0] != 3:
            continue
        candidates = network_states.get((record[11], record[10]), set())
        if len(candidates) != 1:
            ambiguous += len(candidates) > 1
            unmapped += not candidates
            continue
        ordinal = next(iter(candidates))
        repeated += ordinal in boundaries
        boundaries.setdefault(ordinal, []).append(index)
        if record[3] in visit_to_protocol and visit_to_protocol[record[3]] != ordinal:
            raise ValueError("One boundary visit matches conflicting protocol ordinals")
        visit_to_protocol[record[3]] = ordinal
    return boundaries, visit_to_protocol, {
        "mapped_protocol_boundaries": len(boundaries),
        "repeated_preexecution_boundary_visits": repeated,
        "unmatched_boundaries": unmapped,
        "ambiguous_boundaries": ambiguous,
    }


def interval_records(records, boundaries, interval):
    """Require both endpoints; raw visit counters cannot substitute for them."""
    if interval not in boundaries or interval + 1 not in boundaries:
        raise ValueError(f"Missing uniquely aligned BATCH endpoint(s) for interval {interval}")
    start, end = boundaries[interval][-1], boundaries[interval + 1][0]
    if start >= end:
        raise ValueError(f"Nonmonotonic boundaries for interval {interval}")
    if any(r[0] == 3 for r in records[start + 1:end]):
        raise ValueError(f"Unresolved intermediate BATCH boundary in interval {interval}")
    return records[start + 1:end]


def describe(record, protocol_interval=None):
    node = record[46] & 0xFFFF
    if node >= 0x8000:
        node -= 0x10000
    node_captured = bool(record[20]) and 0 <= node < 100
    return {
        "kind": KINDS.get(record[0], f"kind_{record[0]}"),
        "pc": f"0x{record[1]:08X}",
        "timestamp": record[2],
        "boundary_visit_count": record[3],
        "protocol_interval": protocol_interval,
        "sequence": record[4],
        "address": f"0x{record[5]:08X}",
        "width": record[6],
        "value": f"0x{record[7]:08X}",
        "vehicle": f"0x{record[8]:08X}",
        "vehicle_order": record[9],
        "seed": f"0x{record[10]:08X}",
        "gp_e8_time": record[11],
        "generation_gp_1e_pre_instruction": record[12],
        "generation_gp_1c": None,
        "generation_gp_1c_note": "No per-entry snapshot; prior qualifying PRC1 global stores can recover this counter.",
        "arguments": {f"a{i}": f"0x{record[45 + i]:08X}" for i in range(4)},
        "start_node_signed16": node if record[0] == 2 else None,
        "requested_depth": record[47] if record[0] == 2 else None,
        "actual_graph_base_physical": f"0x{record[20]:08X}",
        "actual_graph_base_cached": f"0x{record[20] | 0x80000000:08X}" if record[20] else None,
        "vehicle_offset": f"0x{record[22]:X}" if record[22] != 0xFFFFFFFF else None,
        "graph_offset": f"0x{record[23]:X}" if record[23] != 0xFFFFFFFF else None,
        "f50": f"0x{record[26]:08X}",
        "f58": f"0x{record[27]:08X}",
        "f5c": f"0x{record[28]:08X}",
        "f60": f"0x{record[29]:08X}",
        "f64": f"0x{record[30]:08X}",
        "f9c": f"0x{record[38]:08X}",
        "d00": f"0x{record[39]:08X}",
        "d06_raw32": f"0x{record[40]:08X}",
        "d08": f"0x{record[41]:08X}",
        "d3a_raw32": f"0x{record[42]:08X}",
        "e84_raw32": f"0x{record[43]:08X}",
        "e86_raw32": f"0x{record[44]:08X}",
        "node_snapshot_index": node if node_captured else None,
        "node_snapshot_words": [f"0x{x:08X}" for x in record[49:56]] if node_captured else None,
        "node_generation_tag_at_0x12": (record[53] >> 16) if node_captured else None,
    }


def store_key(record):
    # Exclude host timestamp, hook count and contextual generation. Preserve
    # guest writer, target, width and value; generation alone is not a write.
    return (record[1], record[5], record[6], record[7], record[22], record[23], record[13])


def path_key(record):
    return (record[1], record[8], record[10], record[12], record[20], record[26:56])


def first_difference(left, right, predicate, key, interval):
    a = [r for r in left if predicate(r)]
    b = [r for r in right if predicate(r)]
    for index, (x, y) in enumerate(zip_longest(a, b)):
        if x is None or y is None:
            return {
                "stream_index_in_interval": index,
                "reason": "different observed record count",
                "extra_side": "Sofia" if x is None else "Oscar",
                "extra": describe(y if x is None else x, interval),
            }
        if key(x) != key(y):
            return {
                "stream_index_in_interval": index,
                "reason": "observed state or execution order differs; not proof of upstream cause",
                "oscar": describe(x, interval), "sofia": describe(y, interval),
            }
    return None


def analyze_records(left, right, network_left, network_right):
    states_a, net_a, error_a = network_left
    states_b, net_b, error_b = network_right
    ba, _, stats_a = align_boundaries(left, states_a)
    bb, _, stats_b = align_boundaries(right, states_b)
    common = sorted(net_a.keys() & net_b.keys())
    state_mismatch = next((n for n in common if net_a[n] != net_b[n]), None)
    candidates = [n for n in (error_a, error_b, state_mismatch) if n is not None]
    mismatch = min(candidates) if candidates else None
    initial = [n for n in common if mismatch is not None and n < mismatch]
    result = {
        "schema_version": 2,
        "records": {"Oscar": len(left), "Sofia": len(right)},
        "network_first_mismatch": {"Oscar": error_a, "Sofia": error_b},
        "first_protocol_state_difference": state_mismatch,
        "alignment": {"Oscar": stats_a, "Sofia": stats_b},
        "initial_network_states": [{
            "ordinal": n, "equal": net_a[n] == net_b[n],
            "oscar_time": net_a[n][0], "sofia_time": net_b[n][0],
            "oscar_seed": f"0x{net_a[n][1]:08X}", "sofia_seed": f"0x{net_b[n][1]:08X}",
        } for n in initial],
        "all_initial_network_states_equal": bool(initial) and all(net_a[n] == net_b[n] for n in initial),
        "initial_network_ordinals_complete": mismatch is not None and initial == list(range(1, mismatch)),
        "pregame_excluded": True,
        "excluded_records_before_first_aligned_boundary": {
            "Oscar": min((min(v) for v in ba.values()), default=len(left)),
            "Sofia": min((min(v) for v in bb.values()), default=len(right)),
        },
        "capture_limitations": {
            "graph_store_range_bytes": "0x1C0",
            "graph_node_stride_bytes": "0x1C",
            "graph_store_nodes_covered": 16,
            "graph_store_node_indices": "0..15 only; not the complete graph",
            "node_snapshots": "Entry snapshots can include nodes 0..99; this does not expand store coverage.",
            "gp_1c_generation": "No per-entry snapshot. Stores to gp+0x1C are recorded in the global-store range and may establish its prior value; never infer it from gp+0x1E.",
        },
        "note": "Boundary visit counts are not protocol ordinals. BATCH boundaries match unique per-peer TX TIME/seed. Observed differences alone do not prove a cause.",
    }
    if mismatch is None or mismatch <= 1:
        result["comparison_status"] = "No mismatch with a preceding BATCH interval is available"
        return result
    interval = mismatch - 1
    result["comparison_protocol_interval"] = interval
    try:
        a = interval_records(left, ba, interval)
        b = interval_records(right, bb, interval)
    except ValueError as exc:
        result["comparison_status"] = str(exc)
        return result
    if net_a.get(interval) != net_b.get(interval):
        result["comparison_status"] = "Preceding BATCH states already differ; no equal starting checkpoint"
        return result
    result["comparison_status"] = "Compared completed interval bounded by uniquely aligned TX states"
    result["comparison_endpoints"] = [{
        "ordinal": n,
        "oscar": describe(left[ba[n][-1]], n),
        "sofia": describe(right[bb[n][-1]], n),
    } for n in (interval, mismatch)]
    result["interval_record_counts"] = {"Oscar": len(a), "Sofia": len(b)}
    comparisons = {
        "first_store_difference_in_interval": (lambda r: r[0] == 1, store_key),
        "first_vehicle_store_difference_in_interval": (lambda r: r[0] == 1 and r[22] != 0xFFFFFFFF, store_key),
        "first_path_selector_writer_difference_in_interval": (lambda r: r[0] == 1 and r[22] == 0xD3A, store_key),
        "first_path_entry_difference_in_interval": (lambda r: r[0] == 2, path_key),
    }
    for name, (predicate, key) in comparisons.items():
        result[name] = first_difference(a, b, predicate, key, interval)
    result["path_entries_in_interval"] = {
        "Oscar": [describe(r, interval) for r in a if r[0] == 2],
        "Sofia": [describe(r, interval) for r in b if r[0] == 2],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    left, cap_left = read_trace(args.run / "Oscar.producer.bin")
    right, cap_right = read_trace(args.run / "Sofia.producer.bin")
    logs = [network_index((args.run / f"TM3Online_{side}.rngcaller.trace.log").read_text(
        encoding="utf-8", errors="replace").splitlines()) for side in ("Oscar", "Sofia")]
    result = analyze_records(left, right, *logs)
    result["declared_cap"] = {"Oscar": cap_left, "Sofia": cap_right}
    result["cap_reached"] = {"Oscar": len(left) >= cap_left, "Sofia": len(right) >= cap_right}
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
