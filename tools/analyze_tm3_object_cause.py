"""Decode read-only object trace and align executed BATCH returns by mailbox sequence."""
import argparse
import json
import re
import struct
from collections import Counter
from pathlib import Path

RECORD = struct.Struct('<256I')
MAGIC = 0x31434F54


def read_records(path):
    with path.open('rb') as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError('Missing trace header')
        magic, version, size, cap, total_low, total_high, reason, retained = struct.unpack('<8I', header)
        total = total_low + (total_high << 32)
        if (magic, version, size) != (MAGIC, 2, 1024) or retained != min(total, cap):
            raise ValueError('Unknown trace format')
        result = []
        while True:
            data = stream.read(size)
            if len(data) != size:
                if len(result) != retained or data:
                    raise ValueError('Incomplete frozen ring dump')
                return result, {'retained': retained, 'total_observed': total, 'old_records_evicted': total-retained, 'dump_reason': reason}
            result.append(RECORD.unpack(data))
            if len(result) > cap:
                raise ValueError('Record count exceeds format cap')


def network(text):
    tx = {}
    mismatch = []
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n'):
            continue
        fields = dict(re.findall(r'([\w-]+)=([^\s]+)', line))
        if fields.get('call') != '8003AA98':
            continue
        if line.startswith('TX '):
            seq = int(fields['seq'])
            if seq in tx:
                raise ValueError('Reused TX sequence: cannot align uniquely')
            tx[seq] = {'ordinal': int(fields['ord']), 'time': int(fields['local-time'], 16),
                       'seed': int(fields['local-random'], 16)}
        if 'MISMATCH' in fields.get('sync', ''):
            mismatch.append(int(fields['ord']))
    return tx, min(mismatch) if mismatch else None


def aligned_interval(rows, tx, ordinal):
    bounds = {}
    for index, row in enumerate(rows):
        if row[1] != 0x8003AA98 or row[6] not in tx:
            continue
        checkpoint = tx[row[6]]
        number = checkpoint['ordinal']
        if number not in (ordinal - 1, ordinal):
            continue
        if number in bounds:
            raise ValueError('Ambiguous repeated executed boundary')
        if (row[4], row[5]) != (checkpoint['time'], checkpoint['seed']):
            raise ValueError('Boundary TIME/seed differs from TX; inspect raw trace')
        bounds[number] = index
    if set(bounds) != {ordinal - 1, ordinal} or bounds[ordinal-1] >= bounds[ordinal]:
        raise ValueError('Complete ordered interval not captured')
    return rows[bounds[ordinal - 1] + 1:bounds[ordinal]]


def describe(row):
    hex32 = lambda x: f'0x{x:08X}'
    obj = None
    if row[15] & 2:
        obj = {'address': hex32(row[12]), 'raw_header': [hex32(x) for x in row[64:76]],
               'raw_body_words': [hex32(x) for x in row[76:164]]}
    return {'pc': hex32(row[1]), 'time': hex32(row[4]), 'seed': hex32(row[5]),
            'rng_counter': row[11], 'ra': hex32(row[47]),
            'pending_load_register': row[8], 'pending_load_value': hex32(row[9]),
            'gpr': [hex32(x) for x in row[16:48]], 'valid_mask': row[15],
            'object': obj, 'target_address': hex32(row[13]),
            'target_raw': [hex32(x) for x in row[164:192]],
            'descriptor_address': hex32(row[14]), 'descriptor_raw': [hex32(x) for x in row[192:216]],
            'stack_words': [hex32(x) for x in row[48:64]],
            'globals': [hex32(x) for x in row[216:240]]}


def analyze(run, ordinal=None):
    captures = {}
    for side in ('Oscar', 'Sofia'):
        rows, status = read_records(run / f'{side}.objectcause.bin')
        tx, first = network((run / f'TM3Online_{side}.rngcaller.trace.log').read_text(encoding='utf-8', errors='replace'))
        captures[side] = (rows, status, tx, first)
    if ordinal is None:
        a, b = (captures[s][3] for s in ('Oscar', 'Sofia'))
        if a is None or a != b:
            raise ValueError('No common first mismatch')
        ordinal = a
    result = {'ordinal': ordinal, 'sides': {}, 'limitations': 'Raw pointers are not cross-console identities. Allocation regions may include neighboring bytes. Missing/ambiguous boundaries rejected. Not a full hardware SIO replay.'}
    for side, (rows, status, tx, _) in captures.items():
        interval = aligned_interval(rows, tx, ordinal)
        result['sides'][side] = {'capture': status, 'counts_by_pc': dict(Counter(f'0x{r[1]:08X}' for r in interval)),
                                  'events': [describe(r) for r in interval]}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--ordinal', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = analyze(args.run, args.ordinal)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ordinal': result['ordinal'], 'sides': {s: {'capture': v['capture'], 'counts_by_pc': v['counts_by_pc']} for s, v in result['sides'].items()}}, indent=2))
