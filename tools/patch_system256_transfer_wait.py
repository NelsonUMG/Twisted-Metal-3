"""Build a QA-only SYSTEM256 disc that keeps TM3's wait callback alive."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import tm3_patch_network as network
from audit_tm3_offline_bin import disc_file
from tm3_patch_timer_recovery_v1 import encode_sector

SOURCE = ROOT / 'runtime/system256/TM3_SYSTEM256.bin'
CALLS = (0x80047EA0, 0x80047EB8)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def word(executable, address):
    offset = 0x800 + address - network.TEXT_ADDRESS
    return struct.unpack_from('<I', executable, offset)[0]


def patched_executable(executable):
    if executable[:8] != b'PS-X EXE':
        raise ValueError('SYSTEM256 disc does not contain a PS-X executable')
    if word(executable, network.MAILBOX_ADDRESS) != network.MAILBOX_MAGIC:
        raise ValueError('SYSTEM256 mailbox magic differs')
    if word(executable, network.MAILBOX_ADDRESS + 4) & 0xFFFF != 6:
        raise ValueError('Expected SYSTEM256 ABI-6 mailbox')
    # Verify this exact transfer caller still owns callback table s1=0x800D3280.
    expected = {
        0x80047728: 0x3C080001,
        0x80047D48: 0x3C02800D,
        0x80047D4C: 0x24423280,
        0x80047D54: 0x00408821,
        0x80047E98: network.j_type(0x03, network.FUNCTION_START),
        0x80047EB0: network.j_type(0x03, network.FUNCTION_START),
    }
    for address, value in expected.items():
        if word(executable, address) != value:
            raise ValueError(f'Unexpected transfer/callback code at {address:08X}')
    stub = network.build_stub(mailbox_version=6)
    region_size = network.MAILBOX_ADDRESS - network.FUNCTION_START
    if len(stub) > region_size:
        raise ValueError('Callback-enabled SYSTEM256 stub does not fit the reserved region')
    result = bytearray(executable)
    start = 0x800 + network.FUNCTION_START - network.TEXT_ADDRESS
    result[start:start + region_size] = stub.ljust(region_size, b'\0')
    if word(result, network.MAILBOX_ADDRESS + 4) & 0xFFFF != 6:
        raise AssertionError('Patched stub changed the SYSTEM256 ABI')
    return bytes(result), len(stub)


def patch_disc(source, output, cue_output):
    original, location = disc_file(source, 'SCUS_942.49')
    patched, code_size = patched_executable(original)
    executable_offset = 0x800 + network.FUNCTION_START - network.TEXT_ADDRESS
    region_size = network.MAILBOX_ADDRESS - network.FUNCTION_START
    changed_sectors = {}
    with source.open('rb') as stream:
        position = 0
        while position < region_size:
            lba = location['lba'] + (executable_offset + position) // 2048
            in_sector = (executable_offset + position) % 2048
            count = min(region_size - position, 2048 - in_sector)
            stream.seek(lba * 2352)
            raw = bytearray(stream.read(2352))
            if len(raw) != 2352 or raw[15] != 2 or raw[16:20] != raw[20:24]:
                raise ValueError(f'Unexpected MODE2 sector at LBA {lba}')
            source_bytes = original[executable_offset + position:
                                    executable_offset + position + count]
            target_bytes = patched[executable_offset + position:
                                   executable_offset + position + count]
            if source_bytes != target_bytes:
                raw[24 + in_sector:24 + in_sector + count] = target_bytes
                changed_sectors[lba] = encode_sector(raw)
            position += count
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or cue_output.exists():
        raise FileExistsError('Refusing to overwrite existing QA disc files')
    shutil.copyfile(source, output)
    with output.open('r+b') as stream:
        for lba, raw in changed_sectors.items():
            stream.seek(lba * 2352)
            stream.write(raw)
    updated, updated_location = disc_file(output, 'SCUS_942.49')
    if updated != patched or updated_location != location:
        raise ValueError('Re-extracted QA executable does not match the patched bytes')
    cue_text = source.with_suffix('.cue').read_text(encoding='ascii')
    cue_output.write_text(cue_text.replace(source.name, output.name), encoding='ascii')
    manifest = dict(
        status='qa_only_not_a_release_asset',
        source=str(source), output=str(output),
        source_executable_sha256=digest(original),
        patched_executable_sha256=digest(patched),
        callback_stub_bytes=code_size,
        callback_call_sites=[f'0x{x:08X}' for x in CALLS],
        callback_table='0x800D3280 via s1+8', abi=6,
        changed_raw_sectors=sorted(changed_sectors),
        reextracted_executable_matches=True)
    output.with_suffix('.manifest.json').write_text(
        json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cue-output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(patch_disc(args.source.resolve(), args.output.resolve(),
                                 args.cue_output.resolve()), indent=2))


if __name__ == '__main__':
    main()
