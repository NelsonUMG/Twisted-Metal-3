"""Verify the frozen ordinal3186 capture against the projectile-basis premise.

Intervals are validated at executed BATCH-return boundaries, not hook counts.
Object pairing requires unique matching spawn arguments, type, owner, target
and callbacks. This script is specific to this preserved capture, not a general
cross-console pointer matcher or a counterfactual full-game replay.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from analyze_tm3_object_cause import read_records, network, aligned_interval

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'diagnostics/link_pause_v1/runs/ObjectCauseFast_20261009_194426_718_0fd1b84e'


def body_half(row, offset):
    return struct.unpack_from('<h', struct.pack('<88I',*row[76:164]),offset)[0]


def vector(row, offset, stride=2):
    return tuple(body_half(row,offset+i*stride) for i in range(3))


def one(rows, predicate, description):
    values = [r for r in rows if predicate(r)]
    if len(values) != 1:
        raise ValueError(f'Expected one {description}, got {len(values)}')
    return values[0]


def snapshot(row):
    return {'pc': f'{row[1]:08X}', 'time': row[4], 'seed': f'{row[5]:08X}',
            'mailbox_sequence': row[6], 'object': f'{row[12]:08X}',
            'type': row[64], 'id_word_minus_0c': row[73],
            'callback': f'{row[74]:08X}', 'render_callback': f'{row[75]:08X}',
            'pending_load': [row[8], f'{row[9]:08X}'],
            'forward': vector(row,0x78,6), 'right': vector(row,0x74,6),
            'up': vector(row,0x76,6), 'velocity': vector(row,0x10),
            'position': vector(row,8), 'trail_first': vector(row,0xa8),
            'raw_144': f'{row[76+0x144//4]:08X}'}


def analyze(run):
    result = {'run':str(run), 'first_mismatch':3186, 'sides':{},
              'limits':['No raw heap snapshot before constructor; missing initialization proved by exact instructions.',
                        'Capture snapshots are before their selected instruction; 30BB0 is after 2EF84.',
                        'Unused padding and raw word144 differences are not treated as causes.',
                        'No whole-game replay, live candidate validation or FPS measurement.']}
    for side in ('Oscar','Sofia'):
        path = run/f'{side}.objectcause.bin'
        rows, status = read_records(path)
        tx, first = network((run/f'TM3Online_{side}.rngcaller.trace.log').read_text())
        if first != 3186 or status['dump_reason'] != 3:
            raise ValueError('Not the preserved first RNG mismatch capture')
        birth_interval = aligned_interval(rows,tx,3151)
        spawn = one(birth_interval,lambda r:r[1]==0x8004A38C and tuple(r[20:24])==(8,9,8,0x80166798),'matched spawn')
        birth = one(birth_interval,lambda r:r[1]==0x8004A4F0 and r[15]&2 and r[64]==8
                    and r[76+0xA0//4]==0x80166798 and r[76+0xA4//4]==0x80163030
                    and r[76+0x144//4]>>16==0x0908,'matched type8 return')
        if birth_interval.index(spawn) >= birth_interval.index(birth):
            raise ValueError('Spawn/return order invalid')
        ptr = birth[12]
        history = []
        for start in (3151,3152,3153):
            interval = aligned_interval(rows,tx,start+1)
            pre = one(interval,lambda r:r[1]==0x80030B90 and r[12]==ptr,'pre update')
            post = one(interval,lambda r:r[1]==0x80030BB0 and r[12]==ptr,'post update')
            history.append({'after_network_ordinal':start,'pre':snapshot(pre),'post':snapshot(post)})
        failure = aligned_interval(rows,tx,3186)
        rng_calls = [{'caller':f'{r[47]-8:08X}', 'seed_before':f'{r[5]:08X}',
                      's3':f'{r[35]:08X}'} for r in failure if r[1]==0x8003A0F0]
        with path.open('rb') as stream:
            trace_hash = hashlib.file_digest(stream,'sha256').hexdigest()
        result['sides'][side] = {'capture':status,'spawn_args':[f'{x:08X}' for x in spawn[20:24]],
                                 'trace_sha256':trace_hash,
                                 'birth':snapshot(birth),'history':history,'failure_rng_calls':rng_calls}
    a,b=(result['sides'][s] for s in ('Oscar','Sofia'))
    for key in ('spawn_args',):
        assert a[key]==b[key]
    for key in ('type','id_word_minus_0c','callback','render_callback','forward','velocity','position'):
        assert a['birth'][key]==b['birth'][key],key
    assert a['birth']['forward']==(0,-2585,-3180)
    assert a['birth']['right']!=b['birth']['right']
    assert a['history'][0]['post']['velocity']==b['history'][0]['post']['velocity']
    assert a['history'][0]['post']['trail_first']!=b['history'][0]['post']['trail_first']
    assert a['history'][1]['post']['velocity']!=b['history'][1]['post']['velocity']
    assert a['history'][2]['post']['position']!=b['history'][2]['post']['position']
    assert [r['caller'] for r in a['failure_rng_calls']]==['80028CCC','80028CF0','80021E48']
    assert [r['caller'] for r in b['failure_rng_calls']]==['80028CCC','80028CF0','80021E48','80021E48']
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,default=RUN)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=analyze(args.run)
    payload=json.dumps(result,indent=2)+'\n'
    if args.output:
        if args.output.exists() and args.output.read_text()!=payload:
            raise FileExistsError('Refusing to overwrite a different report')
        if not args.output.exists():
            with args.output.open('x') as stream: stream.write(payload)
    print(json.dumps({'verified':True,'first_mismatch':result['first_mismatch'],
                      'birth':{s:v['birth'] for s,v in result['sides'].items()}},indent=2))
