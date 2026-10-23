"""Correlate same-host QPC brackets; do not confuse intervals with exact instants."""
import argparse,csv,io,json,re
from collections import defaultdict,Counter
from pathlib import Path

def analyze(guest,host):
    events=defaultdict(lambda:defaultdict(list))
    for line in host.splitlines():
        if not line.startswith(('LINK_DETECT ','LINK_PUBLISH ')):continue
        kind=line.split()[0];values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
        events[values['seq']][kind].append(values)
    output=[];excluded=Counter()
    for raw in csv.DictReader(io.StringIO(guest)):
        if None in raw or any(v is None for v in raw.values()):raise ValueError('Incomplete row')
        r={k:int(v) for k,v in raw.items()}
        if not r['valid']:excluded['invalid_scene']+=1;continue
        ev=events[r['sequence']]
        if len(ev['LINK_DETECT'])!=1 or len(ev['LINK_PUBLISH'])!=1:
            excluded['missing_or_duplicate_host_events']+=1;continue
        d=ev['LINK_DETECT'][0];p=ev['LINK_PUBLISH'][0];hz=r['qpc_hz']
        if hz<=0 or hz!=d['hz']:raise ValueError('Clock frequency mismatch')
        if not (r['publish_before']<=r['publish_after']<=r['ready_guest']<=r['resume_guest']
                and r['publish_before']<=d['qpc']<=p['before']<=p['after']
                and p['before']<=r['ready_guest']):
            excluded['invalid_clock_order']+=1;continue
        scale=1000/hz
        output.append({'sequence':r['sequence'],'time':r['time_start'],'map':r['map_start'],'active':r['pop_start'],
            'detect_delay_low_ms':max(0,d['qpc']-r['publish_after'])*scale,
            'detect_delay_high_ms':(d['qpc']-r['publish_before'])*scale,
            'resume_delay_low_ms':max(0,r['resume_guest']-p['after'])*scale,
            'resume_delay_high_ms':(r['resume_guest']-p['before'])*scale,
            'guest_link_span_low_ms':(r['resume_guest']-r['publish_after'])*scale,
            'guest_link_span_high_ms':(r['resume_guest']-r['publish_before'])*scale})
    return {'matched':len(output),'excluded':dict(excluded),'intervals':output,
        'limits':'Host QPC bounds, not guest cycles. Matching requires one process session. Diagnostic IO adds load.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('guest',type=Path);p.add_argument('host',type=Path)
    a=p.parse_args()
    def complete(path):
        raw=path.read_bytes();return raw[:raw.rfind(b'\n')+1].decode('utf-8-sig',errors='replace')
    print(json.dumps(analyze(complete(a.guest),complete(a.host)),indent=2))
