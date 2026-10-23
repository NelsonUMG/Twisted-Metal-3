"""Prepare the isolated twin-console experiment; never install it."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '256mb system'
SOURCE_HASH = '133d4cb7a59c059d99d41d61cca06c1ddf147753f2d951c5c27a6303d737f502'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    for name in ('game', 'src', 'reports', 'runtime'): (OUT / name).mkdir(exist_ok=True)
    protected = {str(p.relative_to(ROOT)): digest(p) for p in [
        ROOT / 'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll',
        ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin',
        ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue',
        ROOT / 'TM3Online_Lobby/runtime/TM3Online.exe', ROOT / 'TM3Online_Lobby/TM3Lobby.exe']}
    before = OUT / 'reports/protected_before.json'
    if not before.exists(): before.write_text(json.dumps(protected, indent=2))
    assert json.loads(before.read_text()) == protected, 'Installed product changed since baseline'
    core = OUT / 'core_source'
    if not core.exists():
        shutil.copytree(ROOT / 'diagnostics/ram256_v1/core', core,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', '*.dll'))
    source = ROOT / 'diagnostics/sqrt_merge_v4/SCUS_942.49.sqrt_merge_v4'
    assert digest(source) == SOURCE_HASH
    data = bytearray(source.read_bytes())
    # Version 6 is deliberately incompatible with the old WAN-cable bridge.
    # Keep the transfer/RNG/TIME/pause logic, but use a synchronous LOCAL core
    # rendezvous. Internet packets will contain controller frames, not BATCHes.
    edits = {0x80047758: (0x24090005, 0x24090006),
             0x80047904: (0x00000005, 0x00000006),
             0x80047A5C: (0x240F0005, 0x240F0006),
             0x80047DF8: (0x24090005, 0x24090006)}
    for pc, (old, new) in edits.items():
        offset = 0x800 + pc - 0x80010000
        assert struct.unpack_from('<I', data, offset)[0] == old, hex(pc)
        struct.pack_into('<I', data, offset, new)
    # ABI 6 readiness is a host-validated 256 MiB capability, not the legacy
    # DRAM-controller/SIO hardware probe. No return-1 bypass: both bits must
    # be present. The adapter verifies retro_get_memory_size before setting it.
    probe = [0x3c088004, 0x9502790a, 0, 0x30420500, 0x38420500,
             0x2c420001, 0x03e00008, 0]
    offset = 0x800 + 0x80047578 - 0x80010000
    assert struct.unpack_from('<I', data, offset)[0] == 0x08011f00
    data[offset:offset+32] = struct.pack('<8I', *probe)
    target = OUT / 'game/SCUS_942.49.system256'
    if target.exists():
        previous = json.loads((OUT/'reports/bin_patch.json').read_text())['candidate_sha256']
        assert digest(target) == previous, 'Unrecognized edits to experimental SCUS'
    target.write_bytes(data)
    tree = ET.parse(ROOT / 'TM3_LINK_ORIGINAL.xml')
    tree.getroot().set('image_name', str(OUT / 'game/TM3_SYSTEM256.bin'))
    tree.getroot().set('cue_sheet', str(OUT / 'game/TM3_SYSTEM256.cue'))
    for element in tree.getroot().iter():
        for attr in ('source', 'file'):
            value = element.get(attr)
            if value: element.set(attr, str((ROOT / value).resolve()))
        if element.tag == 'file' and element.get('name') == 'SCUS_942.49':
            element.set('source', str(target))
    ET.indent(tree, space='    ')
    tree.write(OUT / 'game/disc.xml', encoding='utf-8')
    (OUT / 'reports/bin_patch.json').write_text(json.dumps(dict(
        source_sha256=SOURCE_HASH, candidate_sha256=digest(target),
        abi=6, changes=[dict(pc=hex(pc), old=hex(a), new=hex(b)) for pc, (a,b) in edits.items()],
        readiness_probe='Requires host CONNECTED + verified RAM256 capability bits',
        game_time_checks_removed=False, rng_checks_removed=False,
        production_modified=False, status='experimental_integration_pending'), indent=2))
    print('Prepared:', OUT)


if __name__ == '__main__': main()
