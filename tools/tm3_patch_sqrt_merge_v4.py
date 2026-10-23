"""Fuse two 64-bit input shifts in general sqrt; retain exact arithmetic."""
import json
import struct
import tm3_patch_sqrt_pair_v1 as base

ROOT=base.ROOT
SOURCE=ROOT/'diagnostics/sqrt_dispatch_v3/SCUS_942.49.sqrt_dispatch_v3'
SOURCE_HASH='0f20478978ca38bca642f502161ed38711a161a423ed3098e57fc7a9e4ef4835'
OUT=ROOT/'diagnostics/sqrt_merge_v4'
CAVE=base.CAVE

def helper():
    w=[];labels={};fixes=[]
    def emit(v):w.append(v)
    def label(n):labels[n]=CAVE+len(w)*4
    def branch(rs,target):fixes.append((len(w),rs,target));emit(0)
    branch(10,'odd')
    label('pair')
    emit(0x00045782) # top two bits; also entry branch delay
    emit(0x010A4025)
    # First root/remainder iteration, leaving a0:a1 unshifted.
    emit(0x00024880);emit(0x25290001);emit(0x0109502A)
    branch(10,'first_done');emit(0x00021040)
    emit(0x01094023);emit(0x24420001)
    label('first_done');emit(0x00084080)
    # Next two bits come from bits 29:28 of the unshifted high word.
    emit((4<<16)|(10<<11)|(28<<6)|2)
    emit(base.imm(12,10,10,3));emit(0x010A4025)
    # One 4-bit concatenated shift replaces two 2-bit shifts.
    emit((4<<16)|(4<<11)|(4<<6))
    emit((5<<16)|(10<<11)|(28<<6)|2)
    emit(0x008A2025);emit((5<<16)|(5<<11)|(4<<6))
    emit(0x00021040);emit(0x00024840);emit(0x25290001);emit(0x0109502A)
    branch(10,'second_done');emit(base.imm(9,6,6,-2))
    emit(0x01094023);emit(0x24420001)
    label('second_done');branch(6,'pair');emit(0x00084080)
    emit(0x03E00008);emit(0)
    # Odd count: one unchanged original iteration, then reenter hook if needed.
    label('odd');emit(base.jump(0x80013C44));emit(0x010A4025)
    for i,rs,target in fixes:
        w[i]=base.imm(5,rs,0,(labels[target]-(CAVE+4*i+4))//4)
    return struct.pack('<%dI'%len(w),*w),labels

def build(source):
    if base.digest(source)!=SOURCE_HASH:raise ValueError('Exact DispatchV3 source required')
    payload,labels=helper()
    if len(payload)>base.LIMIT-CAVE:raise ValueError('Helper exceeds existing reserved space')
    if any(source[base.at(CAVE)+140:base.at(base.LIMIT)]):raise ValueError('Unexpected padding')
    # Existing loop tail is retained for an odd leading iteration.
    # Only the known hook and internal old helper may enter the replaced cave.
    for pc in range(0x80010000,0x8007F000,4):
        v=base.word(source,pc);op=v>>26;target=None
        if op in (2,3):target=((pc+4)&0xf0000000)|((v&0x3ffffff)<<2)
        elif op in (1,4,5,6,7):
            n=v&65535;target=pc+4+4*(n-65536 if n&32768 else n)
        if target is not None and CAVE<=target<base.LIMIT and pc!=base.HOOK and not CAVE<=pc<base.LIMIT:
            raise ValueError('Unexpected inbound cave branch')
    for off in range(0x800,len(source)-3,4):
        if CAVE<=struct.unpack_from('<I',source,off)[0]<base.LIMIT:raise ValueError('Embedded cave pointer')
    records=[(base.HOOK,struct.pack('<I',base.jump(CAVE))),
             (CAVE,payload+bytes(base.LIMIT-CAVE-len(payload)))]
    candidate=bytearray(source);ips=b'PATCH'
    for pc,data in records:
        off=base.at(pc);candidate[off:off+len(data)]=data
        ips+=off.to_bytes(3,'big')+len(data).to_bytes(2,'big')+data
    candidate=bytes(candidate);ips+=b'EOF'
    if base.replay_ips(source,ips)!=candidate:raise ValueError('IPS mismatch')
    return candidate,ips,{'format':'TM3_SQRT_MERGE_V4_PATCH','status':'experimental_gameplay_AB_pending',
        'source_sha256':base.digest(source),'candidate_sha256':base.digest(candidate),
        'ips_sha256':base.digest(ips),'helper_bytes':len(payload),
        'labels':{k:f'{v:08X}' for k,v in labels.items()},
        'scope':'Hook jump and existing 176-byte cave only. FastV2 fast path untouched.',
        'limits':'Savings depend on loop count; return-state equivalence is not interrupt or game synchronization proof.'}

def main():
    candidate,ips,meta=build(SOURCE.read_bytes());OUT.mkdir(parents=True,exist_ok=True)
    for name,data in [('SCUS_942.49.sqrt_merge_v4',candidate),('sqrt_merge_v4.ips',ips),
                      ('patch_manifest.json',(json.dumps(meta,indent=2)+'\n').encode())]:
        path=OUT/name
        if path.exists():
            if path.read_bytes()!=data:raise FileExistsError(path)
        else:
            with path.open('xb') as stream:stream.write(data)
    print(json.dumps(meta,indent=2))

if __name__=='__main__':main()
