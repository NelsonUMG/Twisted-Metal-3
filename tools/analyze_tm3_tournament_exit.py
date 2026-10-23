"""Read existing ObjectCause records; do not infer a hang PC from the last hook."""
import argparse
import json
from pathlib import Path
from analyze_tm3_object_cause import read_records, network


def analyze(run):
    result = {'run': str(run), 'sides': {}, 'limitations': [
        'Trace records are selected hooks, not a complete instruction trace.',
        'A missing allocator return does not distinguish allocator, constructor or callee.',
        'Partial final network lines are excluded; capture can extend beyond flushed log.',
        'A completed tournament is user-reported acceptance, not a general stability/FPS guarantee.']}
    for side in ('Oscar', 'Sofia'):
        rows, status = read_records(run / f'{side}.objectcause.bin')
        log = (run / f'TM3Online_{side}.rngcaller.trace.log').read_text(errors='replace')
        tx, mismatch = network(log)
        timers = [(n, r) for n, r in enumerate(rows) if r[15] & 2 and
                  r[64] == 12 and r[77] == 0x800444C8 and r[78:80] == (1, 4)]
        created = [(n, r) for n, r in timers if r[1] == 0x8004A4F0 and r[76] == 120]
        deleted = [(n, r) for n, r in timers if r[1] == 0x8004A668 and r[76] == 0]
        if len(created) != 1 or len(deleted) != 1:
            raise ValueError(f'{side}: expected one complete captured exit timer')
        first, last = created[0], deleted[0]
        if first[0] >= last[0] or first[1][12] != last[1][12]:
            raise ValueError('Timer identity/order mismatch')
        ticks = [r[76] for n, r in timers if first[0] < n < last[0] and r[1] == 0x8004AAE4]
        if ticks != list(range(120, 0, -1)):
            raise ValueError('Countdown not observed exactly once per tick')
        final = rows[-1]
        result['sides'][side] = {
            'capture': status, 'complete_batch_tx': len(tx),
            'last_complete_tx_ordinal': max(v['ordinal'] for v in tx.values()),
            'first_logged_mismatch': mismatch,
            'complete_sync_ok_lines': sum('sync=OK' in line for line in log.splitlines(keepends=True) if line.endswith('\n')),
            'timer': {'object': f'{first[1][12]:08X}', 'creation_time': first[1][4],
                      'deletion_time': last[1][4], 'ticks': len(ticks), 'exit_state_argument': 4},
            'events_after_timer_deletion': len(rows)-last[0]-1,
            'last_observed_hook': {'pc': f'{final[1]:08X}', 'ra': f'{final[47]:08X}',
                                   'time': final[4], 'a0': final[20], 'a1': final[21],
                                   'a2': final[22], 'a3': final[23],
                                   'human_local_remote_total': list(final[219:222]),
                                   'configured_cpu': final[222], 'configured_total': final[223]},
        }
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = analyze(args.run)
    data = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(data, encoding='utf-8')
    print(data)
