"""Offline MIPS path replay from TPC1 observations; no game or emulator launch.

Reconstruct only observed initial bytes, reject unknown reads, implement MIPS
branch/load delays, and substitute only the exact LCG math for the RNG call.
This is a functional routine test, not a hardware/timing/full-game replay.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import analyze_tm3_path_cause as trace
import analyze_tm3_producer_cause as producer
import tm3_patch_path_stamp_v1 as patcher

ROOT = Path(__file__).resolve().parents[1]
PATCH_PCS = (0x80016F14, 0x80016F2C, 0x80016F38, 0x80017190)


def signed(value, bits=32):
    return (value & ((1 << (bits - 1)) - 1)) - (value & (1 << (bits - 1)))


def physical(address):
    return address & 0x1FFFFFFF


def initial_bytes(records):
    """Read-before-write recovery across the recorded path instructions."""
    memory, written = {}, set()
    for r in records:
        op = r[10] >> 26
        if not r[12] or op not in (0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B):
            continue
        address = physical(r[11])
        for i, byte in enumerate(r[13].to_bytes(4, 'little')):
            if address + i not in written:
                previous = memory.setdefault(address + i, byte)
                if previous != byte:
                    raise ValueError(f'unobserved memory mutation at {address+i:08X}')
        if op in (0x28, 0x29, 0x2B):
            written.update(range(address, address + {0x28: 1, 0x29: 2, 0x2B: 4}[op]))
    return memory


class Replay:
    def __init__(self, code, registers, memory, seed, pending=None):
        self.code = code
        self.reg = list(registers)
        self.mem = dict(memory)
        self.seed = seed
        self.pc, self.next_pc = 0x80016EA8, 0x80016EAC
        self.pending = pending
        self.calls, self.steps = 0, 0
        self.pcs = []
        self.reads = []
        self.branches = []
        self.output_address = self.reg[4]
        self.stop = self.reg[31]

    def read(self, addr, width):
        addr = physical(addr)
        try:
            return sum(self.mem[addr+i] << (8*i) for i in range(width))
        except KeyError as e:
            raise ValueError(f'unobserved read {addr:08X}/{width} at PC {self.pc:08X}') from e

    def write(self, addr, value, width):
        addr = physical(addr)
        for i in range(width):
            self.mem[addr+i] = (value >> (8*i)) & 255

    def step(self):
        pc = self.pc
        if pc == 0x8003A0F0:
            # Exact original LCG and returned (seed >> 16) & 0x7fff.
            # The v12 logging cave's scratch regs/cycles are outside this model.
            product = (self.seed * 0x41C64E6D) & 0xFFFFFFFF
            self.seed = (product + 0x3039) & 0xFFFFFFFF
            self.reg[2] = (self.seed >> 16) & 0x7FFF
            self.reg[3], self.reg[4] = 0x41C64E6D, product
            self.calls += 1
            self.pc, self.next_pc = self.reg[31], self.reg[31] + 4
            return
        if pc not in self.code:
            raise ValueError(f'unsupported external PC {pc:08X}')
        ins = self.code[pc]
        op, rs, rt, rd, sh, fn = ins >> 26, (ins >> 21)&31, (ins >> 16)&31, (ins >> 11)&31, (ins >> 6)&31, ins&63
        imm = signed(ins & 0xFFFF, 16)
        a, b = self.reg[rs], self.reg[rt]
        result = None
        load = None
        target = None
        if op == 0:
            if fn == 0: result = (rd, b << sh)
            elif fn == 2: result = (rd, b >> sh)
            elif fn == 3: result = (rd, signed(b) >> sh)
            elif fn == 8: target = a
            elif fn == 0x21: result = (rd, a+b)
            elif fn == 0x23: result = (rd, a-b)
            elif fn == 0x24: result = (rd, a&b)
            elif fn == 0x25: result = (rd, a|b)
            elif fn == 0x2A: result = (rd, int(signed(a)<signed(b)))
            elif fn == 0x2B: result = (rd, int(a<b))
            else: raise ValueError(f'unsupported SPECIAL {ins:08X}')
        elif op in (2, 3):
            target = ((pc+4)&0xF0000000) | ((ins&0x3FFFFFF)<<2)
            if op == 3: result = (31, pc+8)
        elif op in (1, 4, 5, 6, 7):
            cond = {4: a==b, 5: a!=b, 6: signed(a)<=0, 7: signed(a)>0}.get(op)
            if op == 1:
                if rt not in (0, 1): raise ValueError('unsupported REGIMM')
                cond = signed(a)<0 if rt == 0 else signed(a)>=0
            if cond: target = pc+4+(imm<<2)
            self.branches.append((pc, a, b, bool(cond)))
        elif op == 9: result = (rt, a+imm)
        elif op == 10: result = (rt, int(signed(a)<imm))
        elif op == 11: result = (rt, int(a<(imm&0xFFFFFFFF)))
        elif op == 12: result = (rt, a&(ins&0xFFFF))
        elif op == 13: result = (rt, a|(ins&0xFFFF))
        elif op == 15: result = (rt, (ins&0xFFFF)<<16)
        elif op in (0x20,0x21,0x23,0x24,0x25):
            width = {0x20:1,0x21:2,0x23:4,0x24:1,0x25:2}[op]
            address = (a+imm)&0xFFFFFFFF
            value = self.read(address,width)
            self.reads.append((pc,address,width,value))
            if op in (0x20,0x21): value = signed(value,width*8)
            load = (rt,value&0xFFFFFFFF)
        elif op in (0x28,0x29,0x2B):
            self.write(a+imm,b,{0x28:1,0x29:2,0x2B:4}[op])
        else: raise ValueError(f'unsupported {ins:08X} at {pc:08X}')
        if self.pending:
            r,v = self.pending
            if r: self.reg[r] = v
        if result:
            r,v = result
            if r: self.reg[r] = v&0xFFFFFFFF
        self.pending = load
        self.reg[0] = 0
        self.pc,self.next_pc = self.next_pc,((target if target is not None else self.next_pc+4)&0xFFFFFFFF)
        self.pcs.append(pc)
        self.steps += 1

    def run(self, limit=2_000_000):
        while self.pc != self.stop:
            if self.steps >= limit: raise ValueError('instruction budget exceeded')
            self.step()
        count = self.reg[2]
        if count > 100: raise ValueError(f'invalid returned path length {count}')
        return {'instructions': self.steps, 'rng_calls': self.calls,
                'seed_after': f'0x{self.seed:08X}', 'length': count,
                'path': [self.read(self.output_address+i*2,2) for i in range(count)]}


def code_from_bytes(blob):
    base = struct.unpack_from('<I',blob,0x18)[0]
    return {pc:struct.unpack_from('<I',blob,0x800+pc-base)[0]
            for pc in range(0x80016EA8,0x8001746C,4)}


def code_words(path):
    return code_from_bytes(path.read_bytes())


def first_search(records):
    end = next((i for i,r in enumerate(records[1:],1) if r[1]==0x80016EA8),len(records))
    return records[:end]


def replay_records(code, records, memory=None):
    start = records[0]
    if start[1] != 0x80016EA8: raise ValueError('missing search entry')
    pending = (start[8],start[9]) if 0<start[8]<32 else None
    return Replay(code,start[16:48],initial_bytes(records) if memory is None else memory,start[7],pending)


def prior_destination_generation(run, side, entry):
    records,_=producer.read_trace(run/f'{side}.producer.bin')
    candidates=[r for r in records if r[0]==2 and r[3]==entry[3]
                and r[10]==entry[7] and r[45:48]==entry[20:23]]
    if len(candidates)!=1: raise ValueError('ambiguous producer/path correspondence')
    stores=[r for r in records if r[0]==1 and r[5]==physical(entry[44]+0x1C)
            and r[6]==2 and r[4]<candidates[0][4]]
    if not stores: raise ValueError('no observed destination-generation writer')
    last=stores[-1]
    if last[1]!=0x800168B0: raise ValueError('unexpected destination-generation writer')
    return last[7]&0xFFFF


def first_tag_branch(code, search, destination_generation):
    replay=replay_records(code,search)
    replay.write(search[0][44]+0x1C,destination_generation,2)
    while replay.pc!=0x8001719C:
        if replay.steps>1000: raise ValueError('first tag branch not reached')
        replay.step()
    replay.step()
    pc,tag,generation,taken=replay.branches[-1]
    return {'pc':f'0x{pc:08X}', 'node_tag':tag, 'generation':generation,
            'treat_as_new_node':taken, 'seed':f'0x{replay.seed:08X}'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--ordinal',type=int,default=4)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    source=patcher.SOURCE.read_bytes()
    patched,_,metadata=patcher.build(source)
    code=code_from_bytes(source)
    patched_code=code_from_bytes(patched)
    result={'kind':'functional_mips_replay_not_hardware_or_gameplay','interval':args.ordinal,'sides':{}}
    snapshots={}
    for side in ('Oscar','Sofia'):
        states,net,mismatch=trace.network_index(args.run/f'TM3Online_{side}.rngcaller.trace.log')
        _,_,visits,_=trace.scan_trace(args.run/f'{side}.pathcause.bin',states)
        records=list(trace.path_records(args.run/f'{side}.pathcause.bin',args.ordinal,visits))
        search=first_search(records)
        replay=replay_records(code,search)
        actual=replay.run()
        expected_pcs=[r[1] for r in search]
        if replay.pcs != expected_pcs:
            first=next((i for i,(a,b) in enumerate(zip(replay.pcs,expected_pcs)) if a!=b),min(len(replay.pcs),len(expected_pcs)))
            raise ValueError(f'{side}: baseline PC replay differs at {first}, expected {expected_pcs[first:first+3]}, actual {replay.pcs[first:first+3]}')
        expected_reads=[(r[1],r[11],{0x20:1,0x21:2,0x23:4,0x24:1,0x25:2}[r[10]>>26],r[13])
                        for r in search if r[12] and r[10]>>26 in (0x20,0x21,0x23,0x24,0x25)]
        observed=[r for r in replay.reads if physical(r[1])<=0xFFFFFC]
        if [(pc,addr,w,v&((1<<(8*w))-1)) for pc,addr,w,v in expected_reads] != observed:
            raise ValueError(f'{side}: baseline load replay differs')
        gen=prior_destination_generation(args.run,side,search[0])
        result['sides'][side]={'baseline':actual,'all_recorded_pcs_and_loads_match':True,
                               'observed_prior_destination_generation':gen,
                               'baseline_first_tag_branch':first_tag_branch(code,search,gen),
                               'candidate_first_tag_branch':first_tag_branch(patched_code,search,gen)}
        snapshots[side]=(records,search,initial_bytes(search),gen)
    # A controlled counterfactual from the longer Sofia trace: translate only
    # observed tag labels and their shared counter. This is not an invented
    # full Oscar memory dump. Both original baselines above remain unmodified.
    records,search,memory,gen=snapshots['Sofia']
    tags={physical(r[11]) for r in records if r[1] in (0x80017194,0x80016F40,0x80017284)}
    variants=[]
    invariant=None
    for delta in (0,1,17,101,32760,65520):
        variant=dict(memory)
        for addr in tags:
            if addr in variant and addr+1 in variant:
                value=variant[addr]|(variant[addr+1]<<8)
                if value+delta>0xFFFF: raise ValueError('rename would wrap')
                value+=delta
                variant[addr],variant[addr+1]=value&255,value>>8
        run=replay_records(patched_code,search,variant)
        run.write(search[0][44]+0x1C,gen+delta,2)
        actual=run.run()
        if invariant is None: invariant=actual
        if actual!=invariant: raise ValueError('candidate depends on generation label')
        variants.append({'tag_delta':delta,'result':actual})
        if delta==1:
            old=replay_records(code,search,variant)
            old.write(search[0][44]+0x1E,snapshots['Oscar'][1][0][14],2)
            broken=old.run()
            if broken!=result['sides']['Oscar']['baseline']:
                raise ValueError('counterfactual did not reproduce Oscar symptom')
    result['counterfactual']={
        'source':'Sofia first-search observed initial bytes; only bookkeeping labels varied',
        'full_oscar_repaired_snapshot_replay':False,
        'original_with_observed_oscar_counter_and_renamed_tags':broken,
        'candidate_generation_label_invariant':True,
        'variants':variants,
        'limitation':'No unknown bytes fabricated; Oscar full candidate explores uncaptured bytes. No IRQ/timing model. 16-bit wrap not repaired.'}
    result['candidate_sha256']=metadata['candidate_sha256']
    output=json.dumps(result,indent=2)+'\n'
    if args.output: args.output.write_text(output,encoding='utf-8')
    print(output,end='')


if __name__=='__main__':
    main()
