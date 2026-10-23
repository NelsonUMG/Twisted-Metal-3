"""Read only the saved interpreter continuation PC; NOT a live instruction profiler."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import time

from diagnose_tm3_slowdown import Reader, CORE_HASH, CORE_RAM_RVAS, utc

ROOT = Path(__file__).resolve().parents[1]


def symbol_rva(core):
    raw = core.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() not in CORE_RAM_RVAS:
        raise ValueError('Unsupported core hash')
    pe, = struct.unpack_from('<I', raw, 0x3c)
    if raw[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', raw, pe+24)[0] != 0x20b:
        raise ValueError('Expected PE32+')
    imagebase, = struct.unpack_from('<Q', raw, pe+24+24)
    nm = ROOT/'third_party/toolchains/winlibs-x86_64/mingw64/bin/nm.exe'
    symbols = subprocess.check_output([str(nm), str(core)], text=True)
    matches = [int(line.split()[0], 16) for line in symbols.splitlines() if line.split()[-1:] == ['s_cpu']]
    if len(matches) != 1:
        raise ValueError('s_cpu symbol ambiguous')
    # cpu.h: uint32 GPR_full[35]; uint32 BACKED_PC, BACKED_new_PC.
    return matches[0]-imagebase+35*4


def category(pc, pcmap, sqrt_pair=False, sqrt_fast=False):
    # Never attribute patched codecaves using the original function map.
    if sqrt_fast and 0x80047800 <= pc < 0x800478F0:
        return 'sqrt_fast_v2'
    if sqrt_pair and 0x80047B50 <= pc < 0x80047BDC:
        return 'sqrt_pair_v1'
    if 0x80047A00 <= pc < 0x80047B4C:
        return 'BATCH_stub'
    if 0x80047728 <= pc < 0x80047900:
        return 'DIRECT_stub'
    return pcmap.get(pc, 'unmapped')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('--seconds', type=float, default=31)
    args = ap.parse_args()
    if args.seconds < 1:
        ap.error('seconds must be positive')
    run = args.run.resolve()
    context = json.loads((run/'TEST_CONTEXT.json').read_text(encoding='utf-8-sig'))
    core = run/'cores/beetle_psx_libretro.dll'
    rva = symbol_rva(core)
    pcmap = {int(r['pc'], 16): r['function_name'] for r in csv.DictReader((ROOT/'diagnostics/tm3_profile_pcmap_v20.csv').open())}
    out = run/('frame_boundary_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(exist_ok=False)
    readers, counts, pcs, joint, invalid, states = {}, {}, {}, {}, {}, []
    try:
        for p in context['processes']:
            s = p['side']
            readers[s] = Reader(p['pid'], p['executable'], core)
            counts[s], pcs[s], joint[s], invalid[s] = Counter(), Counter(), Counter(), 0
        start, cpu_start = time.monotonic(), time.process_time()
        next_state, rng = start, random.Random(20261017)
        with (out/'observations.jsonl').open('x') as stream:
            while time.monotonic()-start < args.seconds:
                if time.monotonic() >= next_state:
                    states.append({s: r.sample() for s, r in readers.items()})
                    next_state = time.monotonic()+.5
                for s, reader in readers.items():
                    pc_raw = reader.read(reader.base+rva, 8)
                    wrapper, = struct.unpack('<Q', reader.read(reader.base+reader.ram_rva, 8))
                    ram, size = struct.unpack('<QI', reader.read(wrapper, 12))
                    if size != 0x1000000:
                        raise ValueError('RAM changed')
                    mailbox = reader.read(ram+0x47900, 32)
                    game_time, = struct.unpack('<I', reader.read(ram+0x895A8, 4))
                    consistent = pc_raw == reader.read(reader.base+rva, 8)
                    pc, npc = struct.unpack('<II', pc_raw)
                    status, command = struct.unpack_from('<HH', mailbox, 6)
                    seq, = struct.unpack_from('<I', mailbox, 12)
                    row = dict(side=s, elapsed_s=time.monotonic()-start, saved_pc=hex(pc),
                               next_pc=hex(npc), pc_stable_across_read=consistent,
                               mailbox_status=status, mailbox_command=command,
                               mailbox_sequence=seq, game_time=game_time)
                    stream.write(json.dumps(row)+'\n')
                    if consistent:
                        cat = category(pc, pcmap, context.get('sqrt_pair',False),context.get('sqrt_fast',False))
                        counts[s][cat] += 1
                        pcs[s][hex(pc)] += 1
                        joint[s][f'{cat}:command{command}:status{status}'] += 1
                    else:
                        invalid[s] += 1
                # Jitter reduces regular sampling alias; no busy spin or timer change.
                time.sleep(rng.uniform(.002, .005))
        result = dict(captured_utc=utc(), output=str(out), core_sha256=hashlib.sha256(core.read_bytes()).hexdigest().upper(),
                      saved_pc_rva=hex(rva), wall_s=time.monotonic()-start,
                      observer_cpu_s=time.process_time()-cpu_start, sides={}, state_samples=states,
                      limitations=['BACKED_PC is last CPU_Run return state, stale during execution; NOT live PC or instruction-time distribution.',
                                   'Repeated snapshots are not distinct frames. Stable reads do not guarantee atomic guest/RAM state.',
                                   'Original PC map is advisory outside classified patched stubs; no automatic bottleneck verdict.',
                                   'Sampling adds host work; compare observation overhead and preserve baseline logs.'])
        for s in readers:
            result['sides'][s] = dict(stable_observations=sum(counts[s].values()), changed_during_read=invalid[s],
                                     saved_function_histogram=counts[s].most_common(15),
                                     saved_pc_histogram=pcs[s].most_common(20),
                                     mailbox_joint_histogram=joint[s].most_common(20))
        (out/'report.json').write_text(json.dumps(result, indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='state_samples'}, indent=2))
        print('States:', json.dumps({s:{k:sorted({t[s][k] for t in states}) for k in ('active_total','map','pause','state','sync_error')} for s in readers}))
    finally:
        for reader in readers.values():
            reader.close()


if __name__ == '__main__':
    main()
