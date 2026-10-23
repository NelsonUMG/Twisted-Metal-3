"""Reload the original menu/demo resources when returning from another state.

TargetLifetimeV1 changes its roster on linked Quit / tournament completion,
but the original reload gate skips those resources for state 3 -> state 1.
Remove only the previous-state equality restriction for destination state 1.
No forced reset, lookup fallback, role/seed/time edits or new SIO messages.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from tm3_patch_path_stamp_v1 import replay_ips

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'diagnostics/target_lifetime_v1/SCUS_942.49.target_lifetime_v1'
OUT = ROOT/'diagnostics/menu_reload_v1'
SOURCE_HASH = '10a6999dd8e3ae187f9c1cc39e06119c1374b684f620a6381fd3dfabc68bae1c'
HOOK = 0x80045200


def at(pc): return 0x800 + pc - 0x80010000
def word(data, pc): return struct.unpack_from('<I', data, at(pc))[0]
def digest(data): return hashlib.sha256(data).hexdigest()


def build(source):
    if digest(source) != SOURCE_HASH or len(source) != 655360 or source[:8] != b'PS-X EXE':
        raise ValueError('Expected exact TargetLifetimeV1 source')
    expected = {
        0x800451F8: 0x16A20007,  # bne s5,v0,45218; v0=1
        0x800451FC: 0x3C02800D,  # delay: lui v0,800D
        HOOK: 0x16D50005,        # bne s6,s5,45218 (remove only this gate)
        HOOK+4: 0,
        0x80045208: 0x3C03800D,
        0x8004520C: 0x24020001,
        0x80045210: 0x08011487,
        0x80045214: 0xAC622D4C,  # reload=1
        0x80045218: 0xAC402D4C,  # reload=0 for other destinations
        0x8003A3D4: 0x8E82009C,  # caller consumes D2D4C
        0x8003A3DC: 0x10400029,
        0x8003A47C: 0x0C012329,  # original loader 80048CA4
    }
    for pc, value in expected.items():
        if word(source, pc) != value:
            raise ValueError(f'Unexpected instruction at {pc:08X}: {word(source, pc):08X}')
    result = bytearray(source)
    result[at(HOOK):at(HOOK)+4] = b'\0'*4
    result = bytes(result)
    ips = b'PATCH'+at(HOOK).to_bytes(3, 'big')+b'\0\4'+b'\0'*4+b'EOF'
    if replay_ips(source, ips) != result:
        raise ValueError('IPS roundtrip failed')
    diff = {i for i, (old, new) in enumerate(zip(source, result)) if old != new}
    if not diff or not diff <= set(range(at(HOOK), at(HOOK)+4)):
        raise ValueError('Unexpected patch scope')
    meta = {
        'format': 'TM3_MENU_RELOAD_V1_PATCH',
        'status': 'experimental_not_gameplay_tested',
        'source_sha256': digest(source), 'candidate_sha256': digest(result),
        'ips_sha256': digest(ips), 'changed_bytes': len(diff),
        'instruction_address': f'{HOOK:08X}', 'before': '16D50005', 'after': '00000000',
        'effect': 'Always enter the original resource reload when normalized destination state is 1',
        'preserved': ['All bytes outside one instruction', 'Original resource loader and menu cleanup',
                      'TargetLifetime/ProjectileBasis/LinkPause/PathStamp fixes',
                      'RNG/TIME mismatch checks, SIO, guest clock and active gameplay'],
        'limitations': ['Additional asset loading for state 2/3 -> 1, including local return paths',
                        'Not a full CD/GPU replay or proof of successful in-game reconnection',
                        'Does not reset transport roles/counters or reconnect a closed peer',
                        'No FPS improvement claim; inherited RNGCaller timing shim remains'],
    }
    return result, ips, meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify-only', action='store_true')
    args = p.parse_args()
    candidate, ips, meta = build(SOURCE.read_bytes())
    if not args.verify_only:
        files = {OUT/'SCUS_942.49.menu_reload_v1': candidate,
                 OUT/'tm3_menu_reload_v1_from_target_lifetime.ips': ips,
                 OUT/'patch_manifest.json': (json.dumps(meta, indent=2)+'\n').encode()}
        for path, payload in files.items():
            if path.exists() and path.read_bytes() != payload:
                raise FileExistsError(f'Refusing overwrite: {path}')
        OUT.mkdir(parents=True, exist_ok=True)
        for path, payload in files.items():
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(payload)
    print(json.dumps(meta, indent=2))


if __name__ == '__main__':
    main()
