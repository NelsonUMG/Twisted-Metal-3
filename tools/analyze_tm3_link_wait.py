"""Host-observed bridge latency, never guest FPS or pure network RTT."""
import argparse
import json
import math
import re
from pathlib import Path


def records(text):
    result = []
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n') or not line.startswith(('RX_REQUEST ', 'RX_RESPONSE ')):
            continue
        fields = dict(re.findall(r'([\w-]+)=([^\s]+)', line))
        if 'wait_us' not in fields:
            continue
        for key in ('wait_us', 'ready_age_us', 'worker_gap_max_us'):
            fields[key] = float(fields[key])
            if not math.isfinite(fields[key]) or fields[key] < 0:
                raise ValueError('Invalid timing: ' + key)
        for key in ('ord', 'retries', 'send_bytes', 'recv_bytes', 'observed_us', 'ready_us'):
            fields[key] = int(fields[key])
        result.append(fields)
    return result


def summarize(rows):
    if not rows:
        return {'count': 0}
    out = {'count': len(rows), 'retries_total': sum(r['retries'] for r in rows)}
    for key in ('wait_us', 'ready_age_us', 'worker_gap_max_us'):
        values = sorted(r[key] / 1000 for r in rows)
        out[key.replace('_us', '_ms')] = {
            'mean': sum(values) / len(values),
            'p50': values[math.ceil(.50 * len(values)) - 1],
            'p95': values[math.ceil(.95 * len(values)) - 1],
            'max': values[-1],
        }
    out['payload_sizes'] = sorted({(r['send_bytes'], r['recv_bytes']) for r in rows})
    return out


def analyze(path):
    rows = records(path.read_text(encoding='utf-8', errors='replace'))
    gameplay = [r for r in rows if r.get('call') == '8003AA98' and r.get('sync') == 'OK']
    return {'path': str(path.resolve()), 'all_completed': summarize(rows),
            'batch_ord_ge_2_including_synthetic': summarize([r for r in rows if r.get('call') == '8003AA98' and r['ord'] >= 2]),
            'gameplay_sync_ok': summarize(gameplay)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps({'schema': 'tm3_link_wait_v1', 'logs': [analyze(p) for p in args.logs],
        'limitations': 'Starts at worker detection, ends before status=3. Includes peer readiness, scheduling, transport and diagnostics. Not pure RTT, not guest resume, not FPS. Partial final lines ignored; trace has a 50000-event limit.'}, indent=2))
