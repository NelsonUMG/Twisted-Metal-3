"""Initialize type-8 projectile lateral basis before its existing orthonormalizer.

The observed forward vector (0,-2585,-3180) skips the original constructor's
AND guard and causes FUN800150FC to read stale heap halfwords. This isolated
candidate initializes (z,0,-x), or (4096,0,0) for a vertical vector. It preserves
the existing normalization, RNG calls, SIO replacement and mismatch checks.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from tm3_patch_path_stamp_v1 import replay_ips

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'diagnostics/link_pause_v1/SCUS_942.49.link_pause_v1'
OUT = ROOT / 'diagnostics/projectile_basis_v1'
SOURCE_HASH = '0a6ab80e66d75b3134e93703d37d0172ac98ba3259329e29a2e2817440773ff6'
START = 0x8002D8A8
END = 0x8002D8E8
OLD_WORDS = (
    0x87A20028, 0x00000000, 0x1040000C, 0x26640074,
    0x87A2002C, 0x97A3002C, 0x10400009, 0x24050002,
    0xA6630074, 0xA660007A, 0x97A20028, 0x00000000,
    0x00021023, 0xA6620080, 0x26640074, 0x24050002,
)
NEW_WORDS = (
    0x87A20028,  # lh v0,28(sp): forward.x
    0x87A3002C,  # lh v1,2C(sp): forward.z; x load delay
    0x00000000,  # z load delay
    0x00432025,  # or a0,v0,v1
    0x14800002,  # bne a0,zero,8002D8C4
    0x00021023,  # subu v0,zero,v0: branch delay, -x
    0x24031000,  # vertical fallback: right.x = 4096
    0xA6630074,  # sh v1,74(s3): right.x
    0xA660007A,  # sh zero,7A(s3): right.y
    0xA6620080,  # sh v0,80(s3): right.z
    0x26640074,  # addiu a0,s3,74
    0x24050002,  # addiu a1,zero,2
    0x00000000, 0x00000000, 0x00000000, 0x00000000,
)


def at(pc):
    return 0x800 + pc - 0x80010000


def word(blob, pc):
    return struct.unpack_from('<I', blob, at(pc))[0]


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def build(source):
    if digest(source) != SOURCE_HASH:
        raise ValueError('Expected the exact Link Pause V1 source')
    if len(source) != 655360 or source[:8] != b'PS-X EXE':
        raise ValueError('Unexpected source format or size')
    if tuple(word(source, p) for p in range(START, END, 4)) != OLD_WORDS:
        raise ValueError('Constructor instructions differ from audited source')
    if (word(source, END), word(source, END + 4)) != (0x0C00543F, 0x00003021):
        raise ValueError('Expected original FUN800150FC(matrix,2,0) call')
    replacement = struct.pack('<16I', *NEW_WORDS)
    result = source[:at(START)] + replacement + source[at(END):]
    ips = b'PATCH' + at(START).to_bytes(3, 'big') + len(replacement).to_bytes(2, 'big') + replacement + b'EOF'
    if replay_ips(source, ips) != result:
        raise ValueError('IPS does not reproduce candidate')
    # The entire remaining executable is identical, including update2F248,
    # RNG codecave, pause/path fixes, original menus and TIME/RANDOM branches.
    differences = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    if len(result) != len(source) or any(not at(START) <= i < at(END) for i in differences):
        raise ValueError('Change outside constructor block')
    metadata = {
        'format': 'TM3_PROJECTILE_BASIS_V1_PATCH',
        'status': 'experimental_not_gameplay_tested',
        'source_sha256': digest(source), 'candidate_sha256': digest(result),
        'ips_sha256': digest(ips), 'changed_bytes': len(differences),
        'changed_region': '8002D8A8..8002D8E4 (16 in-place instructions)',
        'reason': 'Initialize lateral basis before 800150FC; axis-aligned forward skipped original initialization',
        'changes': [{'pc': f'{START+4*i:08X}', 'old': f'{a:08X}', 'new': f'{b:08X}'}
                    for i, (a, b) in enumerate(zip(OLD_WORDS, NEW_WORDS)) if a != b],
        'preserved': ['Full source outside the 64-byte block', 'Original normalization function and call',
                      'Forward direction', 'RNG and TIME comparisons', 'SIO/NetBridge payload', 'v10/v12 controls'],
        'limitations': ['Actual multiplayer validation pending', 'Does not claim to fix all historical desyncs',
                        'Not a performance optimization or FPS measurement',
                        'Zero forward vector remains degenerate; no invented direction',
                        'Existing update retains its previous basis in axis-aligned cases'],
    }
    return result, ips, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    result, ips, metadata = build(SOURCE.read_bytes())
    if not args.verify_only:
        files = {OUT/'SCUS_942.49.projectile_basis_v1': result,
                 OUT/'tm3_projectile_basis_v1_from_link_pause.ips': ips,
                 OUT/'patch_manifest.json': (json.dumps(metadata, indent=2)+'\n').encode()}
        for path, payload in files.items():
            if path.exists() and path.read_bytes() != payload:
                raise FileExistsError(f'Refusing to overwrite {path}')
        OUT.mkdir(parents=True, exist_ok=True)
        for path, payload in files.items():
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(payload)
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
