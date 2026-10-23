"""Read a live or closed TLC1 capture; report partial tail without inventing records."""
import argparse
import json
import struct
from collections import Counter
from pathlib import Path

GLOBALS = ('demo_option', 'pause', 'current_state', 'requested_state',
           'ui_state', 'load_menu', 'sync_error', 'game_variant',
           'game_active', 'extra_humans', 'victory', 'next_level',
           'boss_intro', 'ending_movie', 'local_humans', 'remote_humans',
           'total_humans', 'cpu_config', 'total_config', 'level',
           'role', 'time', 'seed', 'mailbox_seq', 'mailbox_status_version',
           'object_head', 'sound_head', 'active_total', 'active_humans',
           'active_cpu', 'wait_callback', 'global_3294')


def read_trace(path):
    raw = path.read_bytes()
    if len(raw) < 16:
        raise ValueError('Missing TLC1 header')
    magic, version, size, period = struct.unpack_from('<4I', raw)
    if (magic, version, size) != (0x31434C54, 1, 512) or not period:
        raise ValueError('Unsupported TLC1 header')
    count, partial = divmod(len(raw)-16, size)
    rows = [struct.unpack_from('<128I', raw, 16+n*size) for n in range(count)]
    if any(r[0] not in (1, 2, 3) or r[9] & ~3 for r in rows):
        raise ValueError('Invalid record')
    return rows, {'records': count, 'partial_tail_bytes': partial, 'sample_period': period}


def describe(r):
    return {'kind': r[0], 'pc': f'{r[1]:08X}', 'ra': f'{r[41]:08X}',
            'timestamp_local': r[2], 'eligible_dispatches': r[7]+(r[8]<<32),
            'pending_load': {'register': r[3], 'value': f'{r[4]:08X}'},
            'globals': dict(zip(GLOBALS, r[42:74])),
            'gpr': [f'{v:08X}' for v in r[10:42]], 'valid_mask': r[9],
            'stack': [f'{v:08X}' for v in r[74:106]], 'armed': bool(r[122])}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path)
    args = p.parse_args()
    rows, status = read_trace(args.path)
    samples = [r for r in rows if r[0] & 2][-128:]
    print(json.dumps({'status': status,
                      'last_128_sample_pcs': dict(Counter(f'{r[1]:08X}' for r in samples)),
                      'last_events': [describe(r) for r in rows if r[0] & 1][-5:],
                      'last_sample': describe(samples[-1]) if samples else None}, indent=2))
