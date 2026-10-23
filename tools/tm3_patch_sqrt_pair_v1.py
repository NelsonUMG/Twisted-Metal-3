"""Isolated exact-integer sqrt loop unroll; not a demonstrated FPS fix."""
import hashlib
import json
import struct
from pathlib import Path

from tm3_patch_path_stamp_v1 import replay_ips

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'diagnostics/menu_reload_v1/SCUS_942.49.menu_reload_v1'
OUT = ROOT/'diagnostics/sqrt_pair_v1'
SOURCE_HASH = '21c20f1b142d7d2dcd280db9e588b3d4860eb2b300639c44dd94e85f84e7b87a'
HOOK, CAVE, LIMIT = 0x80013C3C, 0x80047B50, 0x80047C00

def at(pc): return 0x800 + pc - 0x80010000
def word(b, pc): return struct.unpack_from('<I', b, at(pc))[0]
def digest(b): return hashlib.sha256(b).hexdigest()
def imm(op, rs, rt, n): return op<<26 | rs<<21 | rt<<16 | (n&65535)
def jump(pc): return 2<<26 | ((pc>>2)&0x3ffffff)

def helper(source):
    words, labels, fixes = [], {}, []
    def emit(w): words.append(w)
    def label(n): labels[n] = CAVE + 4*len(words)
    def branch(rs, rt, target):
        fixes.append((len(words), rs, rt, target)); emit(0)
    emit(imm(12, 6, 10, 1))           # t2 = count parity
    branch(10, 0, 'second')
    emit(0x00CA3021)                  # addu a2,a2,t2; odd -> next even
    for name in ('first', 'second'):
        label(name)
        for pc in range(0x80013C3C, 0x80013C64, 4):
            if name == 'first' and pc == 0x80013C54: continue
            # Compute trial from the old root; perform root shift in branch delay.
            emit(0x00024880 if name == 'first' and pc == 0x80013C58 else word(source, pc))
        branch(10, 0, name+'_end')
        # First half no decrement; second half accounts for both iterations.
        emit(word(source, 0x80013C54) if name == 'first' else imm(9, 6, 6, -2))
        emit(word(source, 0x80013C6C)); emit(word(source, 0x80013C70))
        label(name+'_end')
        if name == 'second': branch(6, 0, 'first')
        emit(word(source, 0x80013C78)) # residual shift, including last iteration
    emit(0x03E00008); emit(0)
    for i, rs, rt, target in fixes:
        words[i] = imm(5, rs, rt, (labels[target]-(CAVE+4*i+4))//4)
    return struct.pack('<%dI'%len(words), *words)

def build(source):
    if digest(source) != SOURCE_HASH: raise ValueError('Exact MenuReloadV1 source required')
    if any(source[at(CAVE):at(LIMIT)]): raise ValueError('Reserved SIO padding is not zero')
    # This gap follows the BATCH jr ra + delay slot, before the RAM probe.
    if word(source, CAVE-12) != 0x03E00008 or word(source, CAVE-8) != 0:
        raise ValueError('BATCH return boundary changed')
    for pc in range(0x80010000, 0x8007F000, 4):
        w = word(source, pc); op = w>>26; target = None
        if op in (2, 3): target = ((pc+4)&0xf0000000) | ((w&0x3ffffff)<<2)
        elif op in (1, 4, 5, 6, 7):
            n=w&65535; target=pc+4+4*(n-65536 if n&32768 else n)
        if target is not None and CAVE <= target < LIMIT:
            raise ValueError(f'Inbound control flow to cave at {pc:08X}')
        if target is not None and HOOK <= target <= HOOK+4 and not 0x80013C00 <= pc <= 0x80013C80:
            raise ValueError(f'External entry into changed loop at {pc:08X}')
    for offset in range(0x800, len(source)-3, 4):
        value=struct.unpack_from('<I', source, offset)[0]
        if CAVE <= value < LIMIT: raise ValueError('Embedded pointer to reserved padding')
    payload=helper(source)
    if CAVE+len(payload)>LIMIT: raise ValueError('Helper exceeds reserved padding')
    records=[(HOOK,struct.pack('<II',jump(CAVE),0)),(CAVE,payload)]
    result=bytearray(source); ips=b'PATCH'
    for pc,data in records:
        result[at(pc):at(pc)+len(data)]=data
        ips+=at(pc).to_bytes(3,'big')+len(data).to_bytes(2,'big')+data
    result=bytes(result); ips+=b'EOF'
    if replay_ips(source,ips)!=result: raise ValueError('IPS roundtrip failed')
    meta={'format':'TM3_SQRT_PAIR_V1_PATCH','status':'candidate_requires_gameplay_AB',
          'source_sha256':digest(source),'candidate_sha256':digest(result),
          'ips_sha256':digest(ips),'helper_bytes':len(payload),
          'changed_bytes':sum(a!=b for a,b in zip(source,result)),
          'preserved':'All bytes outside loop entry and 80047B50 padding; integer arithmetic, GTE setup, RNG/TIME checks, clock configuration and previous fixes',
          'limits':'Instruction scheduling and guest elapsed cycles change; no proof of whole-game determinism or wall-time improvement. No live writes.'}
    return result,ips,meta

def main():
    result,ips,meta=build(SOURCE.read_bytes())
    OUT.mkdir(parents=True,exist_ok=True)
    for name,data in [('SCUS_942.49.sqrt_pair_v1',result),('sqrt_pair_v1.ips',ips),
                      ('patch_manifest.json',(json.dumps(meta,indent=2)+'\n').encode())]:
        path=OUT/name
        if path.exists():
            if path.read_bytes()!=data: raise FileExistsError(path)
        else:
            with path.open('xb') as f: f.write(data)
    print(json.dumps(meta,indent=2))

if __name__=='__main__': main()
