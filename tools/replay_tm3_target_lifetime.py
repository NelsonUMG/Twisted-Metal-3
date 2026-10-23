"""Bounded MIPS replay of the lifetime helper and original target validator.

Models branch and load delays, rejects missing memory and unknown opcodes.
It does not execute a full game or GTE. The capture replay recreates a minimal
object list from actual pre-death projectile snapshots, then uses the actual
post-respawn vehicle table to demonstrate the address-reuse failure.
"""
import argparse
import json
from pathlib import Path

import tm3_patch_target_lifetime_v1 as patch
from analyze_tm3_object_cause import read_records, network, aligned_interval

GP=0x800894C0
SP=0x1F800300
SENTINEL=0x80000080
RUN=patch.ROOT/'diagnostics/link_pause_v1/runs/ProjectileBasisV1_20261011_040736_063_bfa8d1c0'


def signed(x,bits=32):
    x&=(1<<bits)-1
    return x-(1<<bits) if x&(1<<(bits-1)) else x


class Mips:
    def __init__(self,blob,pc,memory,regs=None):
        self.blob,self.pc,self.next_pc=blob,pc,pc+4
        self.memory=dict(memory)
        self.regs=list(regs) if regs else [0]+[0x76540000+n for n in range(1,32)]
        self.pending=None; self.reads=[]; self.writes=[]; self.pcs=[]

    def run(self,stop,limit=20000):
        for _ in range(limit):
            if self.pc==stop: return self
            pc=self.pc; w=patch.word(self.blob,pc); self.pcs.append(pc)
            op,rs,rt=w>>26,(w>>21)&31,(w>>16)&31
            imm=signed(w&0xffff,16); following=self.next_pc+4
            dest=value=newload=None
            if op==0x23:
                addr=(self.regs[rs]+imm)&0xffffffff
                if addr&3: raise ValueError('Unaligned load')
                self.reads.append(addr); newload=(rt,self.memory[addr])
            elif op==0x2b:
                addr=(self.regs[rs]+imm)&0xffffffff
                if addr&3 or addr not in self.memory: raise ValueError('Unmapped/unaligned store')
                self.memory[addr]=self.regs[rt]; self.writes.append(addr)
            elif op==9: dest,value=rt,self.regs[rs]+imm
            elif op==0xb: dest,value=rt,int(self.regs[rs]<(imm&0xffffffff))
            elif op==0xf: dest,value=rt,(w&0xffff)<<16
            elif op in (4,5,6,7):
                cond={4:self.regs[rs]==self.regs[rt],5:self.regs[rs]!=self.regs[rt],
                      6:signed(self.regs[rs])<=0,7:signed(self.regs[rs])>0}[op]
                if cond: following=pc+4+4*imm
            elif op in (2,3):
                following=((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
                if op==3: dest,value=31,pc+8
            elif op==0:
                rd,fn=(w>>11)&31,w&63
                if w==0: pass
                elif fn==8: following=self.regs[rs]
                elif fn in (0x21,0x23,0x2a):
                    dest=rd
                    value={0x21:lambda:self.regs[rs]+self.regs[rt],
                           0x23:lambda:self.regs[rs]-self.regs[rt],
                           0x2a:lambda:int(signed(self.regs[rs])<signed(self.regs[rt]))}[fn]()
                else: raise ValueError(f'Unsupported SPECIAL {pc:08X} {w:08X}')
            else: raise ValueError(f'Unsupported instruction {pc:08X} {w:08X}')
            if self.pending and self.pending[0]: self.regs[self.pending[0]]=self.pending[1]&0xffffffff
            if dest: self.regs[dest]=value&0xffffffff
            self.regs[0]=0; self.pending=newload
            self.pc,self.next_pc=self.next_pc,following
        raise ValueError('Step limit: malformed loop/list')


def cleanup(blob,dying,nodes):
    """nodes: (header address,type,target); order is the fixture list order."""
    memory={GP+0x1fc:nodes[0][0] if nodes else 0}
    for i,(head,kind,target) in enumerate(nodes):
        memory[head]=kind
        memory[head+8]=nodes[i+1][0] if i+1<len(nodes) else 0
        if kind==8: memory[head+0xd4]=target
    for off in range(-16,0,4): memory[SP+off]=0xFACE0000-off
    regs=[0]+[0x76540000+n for n in range(1,32)]
    regs[17],regs[28],regs[29]=dying,GP,SP
    return Mips(blob,patch.HOOK,memory,regs).run(patch.ORIGINAL_CALLEE),memory,regs


def valid_target(blob,target,table):
    memory={0x800D3234:len(table),**{0x800D3240+4*i:v for i,v in enumerate(table)}}
    regs=[0]*32; regs[4],regs[31]=target,SENTINEL
    return Mips(blob,0x800471D4,memory,regs).run(SENTINEL).regs[2]


def capture_replay():
    source=patch.SOURCE.read_bytes(); candidate,_,_=patch.build(source)
    output={'run':str(RUN),'scope':__doc__,'sides':{}}
    for side in ('Oscar','Sofia'):
        rows,meta=read_records(RUN/f'{side}.objectcause.bin')
        tx,first=network((RUN/f'TM3Online_{side}.rngcaller.trace.log').read_text())
        assert first==3368 and meta['dump_reason']==3
        interval=aligned_interval(rows,tx,3367)
        deletes=[r for r in interval if r[1]==0x8004A668 and r[12]==0x801675D8 and r[64]==0]
        assert len(deletes)==1 and deletes[0][70]==0xB9
        death=deletes[0]; last={}
        for r in rows[:rows.index(death)]:
            if r[15]&2 and r[64]==8 and r[13]==0x801675D8:
                last[r[12]]=r
        # Use the four uniquely born type8 objects in the complete3360 interval.
        births=[r for r in aligned_interval(rows,tx,3361)
                if r[1]==0x8004A4F0 and r[15]&2 and r[64]==8 and r[13]==0x801675D8]
        assert len(births)==4 and len({r[12] for r in births})==4
        nodes=[(r[12]-0x30,8,last[r[12]][13]) for r in births]
        baseline,_,_=cleanup(source,death[12],nodes)
        fixed,_,_=cleanup(candidate,death[12],nodes)
        checkpoint=[r for r in rows if r[1]==0x8003AA98 and tx.get(r[6],{}).get('ordinal')==3367]
        assert len(checkpoint)==1
        table=list(checkpoint[0][227:227+checkpoint[0][224]])
        entries=[]
        for head,kind,target in nodes:
            old=baseline.memory[head+0xd4]; new=fixed.memory[head+0xd4]
            assert old==target==0x801675D8 and new==0
            entries.append({'projectile':f'{head+0x30:08X}', 'old_target':f'{old:08X}',
                            'new_target':f'{new:08X}','original_valid_after_respawn':valid_target(source,old,table),
                            'candidate_valid_after_respawn':valid_target(candidate,new,table)})
        output['sides'][side]={'deleted_vehicle':f'{death[12]:08X}','deleted_id':'B9',
                              'post_respawn_table':[f'{p:08X}' for p in table],'projectiles':entries}
    assert all(p['original_valid_after_respawn']==1 for p in output['sides']['Oscar']['projectiles'])
    assert all(p['original_valid_after_respawn']==0 for p in output['sides']['Sofia']['projectiles'])
    assert all(p['candidate_valid_after_respawn']==0 for side in output['sides'].values() for p in side['projectiles'])
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path); args=parser.parse_args()
    result=capture_replay(); payload=json.dumps(result,indent=2)+'\n'
    if args.output:
        if args.output.exists() and args.output.read_text()!=payload: raise FileExistsError('Refusing changed report')
        if not args.output.exists():
            with args.output.open('x') as stream: stream.write(payload)
    print(payload)
