"""Read-only comparison of completed TPC1 records, including live files.

Reports the first observed difference, not a proven root cause. Pair searches
by order within a BATCH interval, never by process-global path counters.
"""
import argparse
from collections import deque
from itertools import zip_longest
import json
import re
from pathlib import Path
import struct

RECORD = struct.Struct('<64I')


def iter_trace(path):
    snapshot_size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(16)
        if len(header) < 16:
            raise ValueError(f'{path}: incomplete header')
        magic, version, size, cap = struct.unpack('<4I', header)
        if (magic, version, size) != (0x31435054, 1, 256):
            raise ValueError(f'{path}: unsupported header')
        for _ in range((snapshot_size - 16) // 256):
            data = stream.read(256)
            if len(data) != 256:
                break
            yield RECORD.unpack(data)


def network_index(path):
    by_state, by_ordinal = {}, {}
    mismatch = None
    rx = re.compile(r'^TX seq=\d+ ord=(\d+) call=8003AA98 .*local-time=0x([0-9A-Fa-f]+) local-random=0x([0-9A-Fa-f]+)')
    mismatch_rx = re.compile(r'\bord=(\d+).*sync=(?:RANDOM_MISMATCH|TIME_MISMATCH)')
    with path.open('r', encoding='utf-8', errors='replace') as stream:
        for line in stream:
            m = rx.search(line)
            if m:
                ordinal, clock, seed = int(m[1]), int(m[2], 16), int(m[3], 16)
                by_state.setdefault((clock, seed), set()).add(ordinal)
                by_ordinal[ordinal] = (clock, seed)
            m = mismatch_rx.search(line)
            if m and mismatch is None:
                mismatch = int(m[1])
    return by_state, by_ordinal, mismatch


def scan_trace(path, network_states):
    boundaries = {}
    visit_to_protocol = {}
    count = 0
    repeated = 0
    for record in iter_trace(path):
        count += 1
        if record[0] == 1:
            candidates = network_states.get((record[15], record[7]), set())
            if len(candidates) == 1:
                ordinal = next(iter(candidates))
                repeated += ordinal in boundaries
                boundaries[ordinal] = record
                visit_to_protocol[record[3]] = ordinal
    return boundaries, count, visit_to_protocol, repeated


def describe(r):
    return {'pc': f'{r[1]:08X}', 'ordinal_before': r[3], 'path_id': r[4],
            'vehicle_context': f'{r[6]:08X}', 'seed': f'{r[7]:08X}',
            'effective_address': f'{r[11]:08X}', 'ram_raw4': f'{r[13]:08X}',
            'pending_load_register': r[8], 'pending_load_value': f'{r[9]:08X}'}


def path_records(path, ordinal, visit_map=None):
    pending = None
    for r in iter_trace(path):
        matched_ordinal = visit_map.get(r[3]) if visit_map is not None else r[3]
        if matched_ordinal != ordinal or r[0] != 3:
            continue
        # This pre-interrupt observer can revisit a PC before it executes.
        # Preserve raw files; compare the last adjacent observation of that PC.
        if pending is not None and pending[1] != r[1]:
            yield pending
        pending = r
    if pending is not None:
        yield pending


def compare_paths(left, right, ordinal, visit_map_a=None, visit_map_b=None):
    # Only the path body; return/context events are reported separately.
    a = path_records(left, ordinal, visit_map_a)
    b = path_records(right, ordinal, visit_map_b)
    previous_a, previous_b = deque(maxlen=4), deque(maxlen=4)
    count = 0
    for i, (x, y) in enumerate(zip_longest(a, b)):
        if x is None or y is None:
            return {'reason': 'different captured instruction count',
                    'first_unpaired_index': i, 'extra_side': 'Sofia' if x is None else 'Oscar'}
        count += 1
        reason = None
        if x[1] != y[1]:
            reason = 'instruction sequence differs (first branch-path difference)'
        elif x[10] != y[10]:
            reason = 'instruction word differs'
        elif x[1] == 0x80016EA8 and (x[21], x[22], x[7], x[14]) != (y[21], y[22], y[7], y[14]):
            reason = 'search entry differs: start node, requested depth, seed or generation'
        elif x[10] >> 26 in (0x20, 0x21, 0x23, 0x24, 0x25):
            op = x[10] >> 26
            mask = 0xFF if op in (0x20, 0x24) else 0xFFFF if op in (0x21, 0x25) else 0xFFFFFFFF
            if x[12] != y[12]:
                reason = 'different RAM-observation validity'
            elif x[12] and (x[11] != y[11] or (x[13] & mask) != (y[13] & mask)):
                reason = 'first observed unequal memory read/address'
        if reason:
            return {'reason': reason, 'instruction_index_in_interval': i,
                    'oscar': describe(x), 'sofia': describe(y),
                    'preceding_oscar': [describe(r) for r in previous_a],
                    'preceding_sofia': [describe(r) for r in previous_b]}
        previous_a.append(x)
        previous_b.append(y)
    return {'reason': 'no path PC/entry/observed-load difference found in this completed interval',
            'instructions_each': count}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    args = p.parse_args()
    left, right = args.run / 'Oscar.pathcause.bin', args.run / 'Sofia.pathcause.bin'
    states_a, net_a, error_a = network_index(args.run / 'TM3Online_Oscar.rngcaller.trace.log')
    states_b, net_b, error_b = network_index(args.run / 'TM3Online_Sofia.rngcaller.trace.log')
    ba, count_a, visits_a, repeated_a = scan_trace(left, states_a)
    bb, count_b, visits_b, repeated_b = scan_trace(right, states_b)
    common = sorted(ba.keys() & bb.keys())
    net_common = sorted(net_a.keys() & net_b.keys())
    mismatch = next((n for n in net_common if net_a[n] != net_b[n]), None)
    result = {'records': {'Oscar': count_a, 'Sofia': count_b},
              'cap_reached': count_a >= 1048576 or count_b >= 1048576,
              'common_mapped_protocol_boundaries': len(common),
              'first_protocol_state_difference': mismatch,
              'network_reported_mismatch': {'Oscar': error_a, 'Sofia': error_b},
              'repeated_preexecution_boundary_visits': {'Oscar': repeated_a, 'Sofia': repeated_b},
              'note': 'Raw hook visits are not protocol ordinals; aligned by unique local TIME/seed TX evidence.',
              'recent_boundaries': [{'ordinal': n, 'oscar_seed': f'{ba[n][7]:08X}',
                                     'sofia_seed': f'{bb[n][7]:08X}',
                                     'oscar_gp_e8': ba[n][15], 'sofia_gp_e8': bb[n][15]}
                                    for n in common[-8:]]}
    if mismatch is not None and mismatch > 1:
        result['preceding_interval_path_comparison'] = compare_paths(left, right, mismatch - 1, visits_a, visits_b)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
