"""One read-only scan of completed log records, not a background monitor."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re


def complete_prefix(path):
    raw=path.read_bytes()
    end=raw.rfind(b'\n')+1
    data=raw[:end]
    return data.decode('utf-8-sig',errors='replace'),{
        'path':str(path),'complete_prefix_bytes':end,
        'complete_prefix_sha256':hashlib.sha256(data).hexdigest(),
        'incomplete_tail_bytes_excluded':len(raw)-end}


def scan(run,seconds):
    result={'captured_utc':datetime.now(timezone.utc).isoformat(),
            'kind':'one_shot_read_only_live_scan','run':str(run.resolve()),'sides':{}}
    for side in ('Oscar','Sofia'):
        perf,perf_source=complete_prefix(run/f'{side.lower()}.host_performance.csv')
        rows=[]
        for row in csv.DictReader(io.StringIO(perf)):
            if None in row or any(value is None for value in row.values()):continue
            values={key:float(value) for key,value in row.items()}
            if all(math.isfinite(v) for v in values.values()):rows.append(values)
        if not rows:raise ValueError(f'{side}: no complete performance windows')
        last=rows[-1]['elapsed_s']
        chosen=[row for row in rows if row['elapsed_s']>last-seconds and row['window_s']>0]
        wall=sum(row['window_s'] for row in chosen)
        frames=sum(row['core_frames'] for row in chosen)
        trace,trace_source=complete_prefix(run/f'TM3Online_{side}.rngcaller.trace.log')
        lines=trace.splitlines()
        bad=[line for line in lines if 'sync=RANDOM_MISMATCH' in line or 'sync=TIME_MISMATCH' in line]
        matches=[line for line in lines if 'call=8003AA98' in line and 'sync=OK' in line]
        result['sides'][side]={
            'performance_source':perf_source,'network_source':trace_source,
            'window_end_elapsed_s':last,'sampled_wall_s':wall,'performance_rows':len(chosen),
            'core_calls_per_s':frames/wall,
            'core_ms_mean_weighted':sum(r['core_ms_mean']*r['core_frames'] for r in chosen)/frames if frames else 0,
            'core_ms_max':max(r['core_ms_max'] for r in chosen),
            'net_poll_ms_mean_weighted':sum(r['net_poll_ms_mean']*r['core_frames'] for r in chosen)/frames if frames else 0,
            'largest_window_frame_interval_p95_ms':max(r['frame_interval_ms_p95'] for r in chosen),
            'frame_interval_ms_max':max(r['frame_interval_ms_max'] for r in chosen),
            'time_units_per_s':sum(r['time_steps'] for r in chosen)/wall,
            'time_discontinuities':sum(r['time_discontinuities'] for r in chosen),
            'video_callbacks_per_s':sum(r['video_callbacks'] for r in chosen)/wall,
            'paint_calls_per_s':sum(r['paint_calls'] for r in chosen)/wall,
            'paint_ms_per_wall_second':sum(r['paint_ms'] for r in chosen)/wall,
            'batch_pending_sample_fraction':sum(r['batch_pending_samples'] for r in chosen)/frames if frames else 0,
            'first_mismatch':bad[0] if bad else None,'mismatch_records':len(bad),
            'last_complete_sync_ok':matches[-1] if matches else None,
        }
    result['limitations']=[
        'Core calls, callbacks, repaints and TIME units are not unique visible game FPS.',
        'Pending sample fraction is not wall-time blocked fraction or network latency.',
        'Sides are read sequentially and windows are not an atomic shared snapshot.',
        'One scan only; game instrumentation continues logging independently.',
    ]
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--seconds',type=float,default=30)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.seconds<=0:raise ValueError('Window must be positive')
    output=json.dumps(scan(args.run,args.seconds),indent=2)+'\n'
    if args.output:args.output.write_text(output,encoding='utf-8')
    print(output)
