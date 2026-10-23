"""Analyze complete diagnostic intervals; eligible dispatches, not wall FPS."""
import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def analyze(path, population=8):
    raw=path.read_bytes()
    complete=raw[:raw.rfind(b'\n')+1]
    labels=json.loads((ROOT/'diagnostics/guest_cost_v1/function_ids.json').read_text())
    counts=Counter(); phases=Counter(); valid=invalid=0; previous=0; cycles=frames=dispatches=0
    groups=Counter()
    for row in csv.DictReader(io.StringIO(complete.decode())):
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Malformed complete row')
        values={k:int(v) for k,v in row.items() if k!='function_counts'}
        if values['tick']!=previous+1:
            raise ValueError('Missing/duplicate tick')
        previous=values['tick']
        items=[p.split(':') for p in row['function_counts'].split(';') if p]
        hist={int(k):int(v) for k,v in items}
        if len(hist)!=len(items) or any(k<0 or k>=len(labels) or v<0 for k,v in hist.items()):
            raise ValueError('Invalid function histogram')
        if sum(hist.values())!=values['dispatches']:
            raise ValueError('Dispatch total differs from histogram')
        groups[(values['map'],values['active_start'],values['active_end'],values['valid'])]+=1
        if not values['valid'] or values['active_start']!=population or values['active_end']!=population:
            invalid+=1;continue
        marks=[0]+[values[k] for k in ('published_at','returned_at','update_done_at','render_done_at')]+[values['dispatches']]
        if values['mark_mask']!=15 or marks!=sorted(marks) or values['time_end']!=values['time_start']+1:
            raise ValueError('Invalid supposedly valid interval')
        valid+=1; counts.update(hist);dispatches+=values['dispatches']
        cycles+=values['guest_cycle_span'];frames+=values['frame_crossings']
        for key,a,b in zip(('publish_setup','mailbox_wait_and_return','post_link_world_update','inputs_and_render','tail_to_next_batch'),marks,marks[1:]):
            phases[key]+=b-a
    return dict(source=str(path),valid_intervals=valid,excluded_intervals=invalid,
                partial_tail_bytes=len(raw)-len(complete),population=population,
                scene_groups=[dict(map=g[0],active_start=g[1],active_end=g[2],valid=g[3],intervals=n) for g,n in groups.items()],
                dispatches=dispatches,guest_cycles_per_interval=cycles/valid if valid else None,
                frame_crossings_per_interval=frames/valid if valid else None,
                phases=[dict(name=k,dispatches=v,share=v/dispatches if dispatches else None) for k,v in phases.items()],
                functions=[dict(name=labels[k],dispatches=v,share=v/dispatches if dispatches else None) for k,v in counts.most_common(25)],
                limitations=['Exclusive eligible pre-dispatch counts, not CPU time or retired instructions; IRQ-flagged dispatches excluded.',
                             'Host instrumentation changes scheduling; use uninstrumented matching scenes for speed validation.',
                             'Endpoint population checks can miss transient changes. Inspect scene_groups; do not combine different maps for causal comparisons.',
                             'Network TIME/RANDOM logs must also be checked for corresponding sequences.',
                             'Final incomplete interval is not written; maximum 3000 flushed intervals.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('logs',nargs='+',type=Path)
    p.add_argument('--population',type=int,default=8)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=json.dumps([analyze(path,args.population) for path in args.logs],indent=2)
    if args.output:
        with args.output.open('x') as f:f.write(result+'\n')
    print(result)
