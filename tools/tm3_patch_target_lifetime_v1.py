"""Clear type-8 target references in vehicle destruction, before allocator reuse.

Hook the vehicle destructor's existing call to remove it from the active table.
Walk the main object list without callbacks, allocation, RNG or list mutations;
clear only type8.body+A4 == dying vehicle. Tail-call the original table cleanup.
The leaf helper uses audited zero space in the already replaced SIO routine.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from tm3_patch_path_stamp_v1 import replay_ips

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'diagnostics/projectile_basis_v1/SCUS_942.49.projectile_basis_v1'
OUT = ROOT/'diagnostics/target_lifetime_v1'
SOURCE_HASH = '03790248324ebbfddf19c633d9f7c6022adcf2abeb806b1621aa59f5279b6836'
HOOK, CAVE, CAVE_LIMIT = 0x80018D44, 0x80047C80, 0x80047D3C
ORIGINAL_CALLEE = 0x80047014


def at(pc): return 0x800 + pc - 0x80010000
def word(data,pc): return struct.unpack_from('<I',data,at(pc))[0]
def digest(data): return hashlib.sha256(data).hexdigest()
def imm(op,rs,rt,value): return op<<26 | rs<<21 | rt<<16 | (value&0xffff)
def jump(op,target): return op<<26 | (target>>2 & 0x3ffffff)


def helper():
    words=[]; labels={}; fixups=[]
    def emit(w): words.append(w)
    def label(name): labels[name]=CAVE+len(words)*4
    def branch(op,rs,rt,name):
        fixups.append((len(words),op,rs,rt,name)); emit(0)
    # Preserve all extra scratch registers. Original a0/ra/sp semantics remain.
    emit(imm(9,29,29,-16))
    for offset,reg in enumerate((8,9,10)): emit(imm(0x2b,29,reg,4*offset))
    emit(imm(0x23,28,8,0x1fc))   # t0 = header head at GP+1FC (800896BC)
    emit(imm(9,0,9,8))           # t1 = type8; t0 load delay
    label('loop')
    branch(4,8,0,'done'); emit(0)
    emit(imm(0x23,8,10,0)); emit(0)
    branch(5,10,9,'next'); emit(0)
    emit(imm(0x23,8,10,0xd4)); emit(0) # header30 + bodyA4
    branch(5,10,4,'next'); emit(0)
    emit(imm(0x2b,8,0,0xd4))
    label('next')
    emit(imm(0x23,8,8,8)); emit(0) # header next pointer, not spatial list
    emit(jump(2,labels['loop'])); emit(0)
    label('done')
    for offset,reg in enumerate((8,9,10)): emit(imm(0x23,29,reg,4*offset))
    emit(imm(9,29,29,16))         # t2 load delay; restore stack
    emit(jump(2,ORIGINAL_CALLEE)); emit(0) # preserve ra from original jal site
    for index,op,rs,rt,name in fixups:
        delta=(labels[name]-(CAVE+index*4+4))//4
        if not -32768<=delta<=32767: raise ValueError('Branch overflow')
        words[index]=imm(op,rs,rt,delta)
    return struct.pack('<%dI'%len(words),*words)


def build(source):
    if digest(source)!=SOURCE_HASH or len(source)!=655360 or source[:8]!=b'PS-X EXE':
        raise ValueError('Expected exact Projectile Basis V1 source')
    # Structural premises: type0 destructor, type8 list routing/size and main list.
    expected={HOOK:jump(3,ORIGINAL_CALLEE),HOOK+4:0x02202021,
              0x8007F278:0x80018CAC,0x8004A4C0:0x24020016,
              0x8004A4DC:0x3C058009,0x8004A4E0:0x24A596C0,
              0x8004A4CC:0x3C058009,0x8004A4D0:0x24A596BC,
              0x8004AAEC:0x8E100008,0x8004AB98:0x8F8401FC,
              0x8004A5C0:jump(3,0x8004A1F0),0x8004A550:0x8E230000,
              0x8002ECA0:0x8E5000A4,0x8002ECCC:0x12000097}
    for pc,old in expected.items():
        if word(source,pc)!=old: raise ValueError(f'Structural premise failed {pc:08X}: {word(source,pc):08X}')
    payload=helper()
    if CAVE+len(payload)>CAVE_LIMIT or any(source[at(CAVE):at(CAVE_LIMIT)]):
        raise ValueError('Helper does not fit verified zero region')
    # Refuse direct inbound control flow or embedded pointer to the reserved gap.
    # Scan the text region, not arbitrary overlays; source hash additionally locks provenance.
    for pc in range(0x80010000,0x8007F000,4):
        w=word(source,pc); op=w>>26; target=None
        if op in (2,3): target=(pc+4)&0xf0000000 | (w&0x3ffffff)<<2
        elif op in (1,4,5,6,7):
            off=w&0xffff; off=off-65536 if off&0x8000 else off
            target=pc+4+4*off
        if target is not None and CAVE<=target<CAVE_LIMIT:
            raise ValueError(f'Inbound original control flow {pc:08X}->{target:08X}')
    for offset in range(0x800,len(source)-3,4):
        value=struct.unpack_from('<I',source,offset)[0]
        if CAVE<=value<CAVE_LIMIT: raise ValueError('Embedded original pointer into reserved gap')
    result=bytearray(source)
    records=[(HOOK,struct.pack('<I',jump(3,CAVE))),(CAVE,payload)]
    ips=bytearray(b'PATCH')
    for pc,data in records:
        result[at(pc):at(pc)+len(data)]=data
        ips+=at(pc).to_bytes(3,'big')+len(data).to_bytes(2,'big')+data
    ips+=b'EOF'; result,ips=bytes(result),bytes(ips)
    if replay_ips(source,ips)!=result: raise ValueError('IPS roundtrip failed')
    allowed={at(pc)+i for pc,data in records for i in range(len(data))}
    diff={i for i,(a,b) in enumerate(zip(source,result)) if a!=b}
    if not diff<=allowed or len(source)!=len(result): raise ValueError('Unexpected byte changes')
    metadata={'format':'TM3_TARGET_LIFETIME_V1_PATCH','status':'experimental_not_gameplay_tested',
              'source_sha256':digest(source),'candidate_sha256':digest(result),'ips_sha256':digest(ips),
              'changed_bytes':len(diff),'hook':f'{HOOK:08X}','helper':f'{CAVE:08X}',
              'helper_bytes':len(payload),'tail_call':f'{ORIGINAL_CALLEE:08X}',
              'scope':'Only type8+A4 targets of the dying type0 vehicle; before table removal and heap free',
              'preserved':['Original destructor/table cleanup','RNG and TIME checks','SIO protocol and guest clock configuration',
                           'ProjectileBasisV1 and LinkPause/PathStamp fixes','All source bytes outside hook/helper'],
              'limitations':['Not a full gameplay/GTE replay','No claim that other object pointer fields are fixed',
                             'Linear scan at vehicle destruction has guest/host cost; no FPS guarantee',
                             'Valid original main object list is assumed; no arbitrary corruption recovery']}
    return result,ips,metadata


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--verify-only',action='store_true'); args=p.parse_args()
    result,ips,meta=build(SOURCE.read_bytes())
    if not args.verify_only:
        files={OUT/'SCUS_942.49.target_lifetime_v1':result,OUT/'tm3_target_lifetime_v1_from_projectile_basis.ips':ips,
               OUT/'patch_manifest.json':(json.dumps(meta,indent=2)+'\n').encode()}
        for path,payload in files.items():
            if path.exists() and path.read_bytes()!=payload: raise FileExistsError(f'Refusing overwrite: {path}')
        OUT.mkdir(parents=True,exist_ok=True)
        for path,payload in files.items():
            if not path.exists():
                with path.open('xb') as stream: stream.write(payload)
    print(json.dumps(meta,indent=2))


if __name__=='__main__': main()
