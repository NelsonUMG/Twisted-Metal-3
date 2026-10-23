"""Exact 32-bit integer fast path, retaining SqrtPairV1 for all other inputs."""
import json
import struct
from pathlib import Path
import tm3_patch_sqrt_pair_v1 as base

ROOT=base.ROOT
SOURCE=ROOT/'diagnostics/sqrt_pair_v1/SCUS_942.49.sqrt_pair_v1'
SOURCE_HASH='fa86dc21e4d72188fe274e20bf9224d0f9c43079845b3bf5da22cef45657c382'
OUT=ROOT/'diagnostics/sqrt_fast_v2'
HOOK,CAVE,LIMIT=0x80013C00,0x80047800,0x80047900
at,word,digest,imm,jump=base.at,base.word,base.digest,base.imm,base.jump

def helper():
    words=[];labels={};fixes=[]
    def emit(w):words.append(w)
    def label(n):labels[n]=CAVE+4*len(words)
    def branch(rs,rt,target):fixes.append((len(words),rs,rt,target));emit(0)
    branch(4,0,'fallback');emit(0x4884F000) # Same GTE LZCS write on BOTH paths.
    branch(6,0,'fallback');emit(0x24020000)
    label('fast')
    emit(0x24080000);emit(0x240B0020);emit(0x24060010);emit(0x00A02021)
    label('loop')
    for i in range(4):
        emit(0x00045782);emit(0x010A4025);emit(0x00042080)
        # trial = old_root*4+1; shift root in conditional branch delay.
        if i==3:emit(0x00021040)
        emit(0x00024840 if i==3 else 0x00024880)
        emit(0x25290001);emit(0x0109502A)
        branch(10,0,f'end{i}')
        emit(imm(9,6,6,-4) if i==3 else 0x00021040)
        emit(0x01094023);emit(0x24420001)
        label(f'end{i}')
        if i==3:branch(6,0,'loop')
        emit(0x00084080)
    # Original shifts duplicated low word through a0; final a0 is input low,
    # a1 is zero. Preserve all scratch outputs, not only returned v0.
    emit(0x00A02021);emit(0x03E00008);emit(0x00002821)
    label('fallback')
    emit(0x24020000);emit(jump(HOOK+8));emit(0)
    for i,rs,rt,target in fixes:words[i]=imm(5,rs,rt,(labels[target]-(CAVE+4*i+4))//4)
    return struct.pack('<%dI'%len(words),*words),labels

def build(source):
    if digest(source)!=SOURCE_HASH:raise ValueError('Exact SqrtPairV1 source required')
    if word(source,HOOK)!=0x4884F000 or word(source,HOOK+4)!=0x24020000:raise ValueError('Entry differs')
    if any(source[at(CAVE):at(LIMIT)]):raise ValueError('DIRECT padding not zero')
    # DIRECT stub failure return at477EC, delay at477F0; padding from477F4.
    if word(source,0x800477EC)!=0x03E00008 or word(source,0x800477F0)!=0:raise ValueError('DIRECT boundary differs')
    payload,labels=helper()
    if len(payload)>LIMIT-CAVE:raise ValueError('Helper too large')
    for pc in range(0x80010000,0x8007F000,4):
        w=word(source,pc);op=w>>26;target=None
        if op in (2,3):target=((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
        elif op in (1,4,5,6,7):
            n=w&65535;target=pc+4+4*(n-65536 if n&32768 else n)
        if target is not None and (CAVE<=target<LIMIT or target==HOOK+4):
            raise ValueError(f'Inbound to replaced region: {pc:08X}')
    for off in range(0x800,len(source)-3,4):
        v=struct.unpack_from('<I',source,off)[0]
        if CAVE<=v<LIMIT or v==HOOK+4:raise ValueError('Embedded pointer to replaced region')
    result=bytearray(source);ips=b'PATCH'
    for pc,data in [(HOOK,struct.pack('<II',jump(CAVE),0)),(CAVE,payload)]:
        result[at(pc):at(pc)+len(data)]=data
        ips+=at(pc).to_bytes(3,'big')+len(data).to_bytes(2,'big')+data
    result=bytes(result);ips+=b'EOF'
    if base.replay_ips(source,ips)!=result:raise ValueError('IPS mismatch')
    return result,ips,{'format':'TM3_SQRT_FAST_V2_PATCH','status':'candidate_gameplay_validation_pending',
        'source_sha256':digest(source),'candidate_sha256':digest(result),'ips_sha256':digest(ips),
        'helper_bytes':len(payload),'labels':{k:f'{v:08X}' for k,v in labels.items()},
        'changed_bytes':sum(a!=b for a,b in zip(source,result)),
        'fast_condition':'a0 == 0 and a2 == 0; unsigned low a1 unrestricted',
        'preserved':'All other inputs use existing SqrtPairV1; all bytes outside entry and DIRECT padding unchanged',
        'limits':'Guest instruction schedule changes. No global speed or determinism claim; fallback has dispatch overhead.'}

def main():
    result,ips,meta=build(SOURCE.read_bytes());OUT.mkdir(parents=True,exist_ok=True)
    for name,data in [('SCUS_942.49.sqrt_fast_v2',result),('sqrt_fast_v2.ips',ips),('patch_manifest.json',(json.dumps(meta,indent=2)+'\n').encode())]:
        path=OUT/name
        if path.exists():
            if path.read_bytes()!=data:raise FileExistsError(path)
        else:
            with path.open('xb') as f:f.write(data)
    print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
