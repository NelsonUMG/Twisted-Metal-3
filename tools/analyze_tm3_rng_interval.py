"""Align an RNGCaller ring to the exact BATCH interval preceding a mismatch.

Reject ambiguous seeds, missing endpoints and reseeds: a shared LCG suffix
alone is not a protocol-aligned causal history.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from analyze_rngcaller_dumps import load_calls
from analyze_tm3_producer_cause import network_index


def interval_calls(calls, start, end):
    if start == end:
        raise ValueError('Equal endpoints do not establish an interval from this ring')
    starts=[i for i,c in enumerate(calls) if c.seed_before==start]
    ends=[i for i,c in enumerate(calls) if c.seed_after==end]
    if len(starts)!=1 or len(ends)!=1 or ends[0]<starts[0]:
        raise ValueError('Missing or ambiguous ring endpoints')
    chosen=calls[starts[0]:ends[0]+1]
    for a,b in zip(chosen,chosen[1:]):
        if a.seed_after!=b.seed_before or b.logical!=a.logical+1:
            raise ValueError('Reseed or ring discontinuity inside interval')
    return chosen


def describe(calls):
    return {'calls':len(calls),
            'logical_first':calls[0].logical if calls else None,
            'logical_last':calls[-1].logical if calls else None,
            'callers':{f'0x{k:08X}':v for k,v in Counter(c.caller for c in calls).items()},
            'sequence':[f'0x{c.caller:08X}' for c in calls],
            'seed_before':f'0x{calls[0].seed_before:08X}' if calls else None,
            'seed_after':f'0x{calls[-1].seed_after:08X}' if calls else None}


def analyze(run):
    networks={}
    for side in ('Oscar','Sofia'):
        log=(run/f'TM3Online_{side}.rngcaller.trace.log').read_text(encoding='utf-8',errors='replace')
        networks[side]=network_index(log.splitlines())
    errors=[x[2] for x in networks.values()]
    if None in errors or errors[0]!=errors[1] or errors[0]<=1:
        raise ValueError('A common first mismatch with a prior interval is required')
    ordinal=errors[0]
    checkpoints=[networks[s][1][ordinal-1] for s in ('Oscar','Sofia')]
    if checkpoints[0]!=checkpoints[1]:raise ValueError('Preceding TIME/seed already differ')
    result={'mismatch_ordinal':ordinal,'interval':ordinal-1,
            'preceding_time':f'0x{checkpoints[0][0]:X}',
            'common_start_seed':f'0x{checkpoints[0][1]:08X}','sides':{}}
    chosen={}
    for side in ('Oscar','Sofia'):
        time,end=networks[side][1][ordinal]
        calls=load_calls(run/f'TM3Online_{side}.rngcaller.calls.csv')
        chosen[side]=interval_calls(calls,checkpoints[0][1],end)
        result['sides'][side]={'mismatch_time':f'0x{time:X}',**describe(chosen[side])}
    a,b=chosen['Oscar'],chosen['Sofia']
    prefix=0
    for x,y in zip(a,b):
        if (x.seed_before,x.seed_after,x.caller)!=(y.seed_before,y.seed_after,y.caller):break
        prefix+=1
    result['identical_rng_prefix_calls']=prefix
    result['remaining']={side:describe(calls[prefix:]) for side,calls in chosen.items()}
    result['limitations']='Caller/seed capture, not producer arguments, vehicle identities, render visibility, elapsed time or FPS. Respawn attribution requires further capture.'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=json.dumps(analyze(args.run),indent=2)+'\n'
    if args.output:args.output.write_text(output,encoding='utf-8')
    print(output)
