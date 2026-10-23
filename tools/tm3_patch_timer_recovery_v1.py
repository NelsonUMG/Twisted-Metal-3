"""Create an isolated one-word TimerRecoveryV1 disc from audited SqrtMergeV4."""
import hashlib
import json
from pathlib import Path
import shutil
import struct

from audit_tm3_offline_bin import disc_file, EXPECTED, ROOT, word

PC = 0x8003E160
OLD = 0x1040000B
OFFSET = 0x800 + PC - 0x80010000
OUT = ROOT / 'diagnostics/timer_recovery_v1'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def patch_executable(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise ValueError('Exact audited SqrtMergeV4 executable required')
    if word(source, PC) != OLD or word(source, PC+4) != 0:
        raise ValueError('Branch or delay slot changed')
    result = bytearray(source)
    struct.pack_into('<I', result, OFFSET, 0)
    return bytes(result)


def encode_sector(raw):
    """Regenerate MODE2 Form1 EDC and Reed-Solomon P/Q parity."""
    sector = bytearray(raw)
    edc = 0
    for value in sector[16:2072]:
        edc ^= value
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
    struct.pack_into('<I', sector, 2072, edc)
    forward, backward = [0]*256, [0]*256
    for i in range(256):
        value = (i << 1) ^ (0x11D if i & 128 else 0)
        forward[i] = value
        backward[i ^ value] = i
    header = sector[12:16]
    sector[12:16] = bytes(4)
    def parity(major_count, minor_count, major_mult, minor_inc, destination):
        size = major_count * minor_count
        for major in range(major_count):
            index = (major >> 1) * major_mult + (major & 1)
            a = b = 0
            for _ in range(minor_count):
                value = sector[12+index]
                index = (index + minor_inc) % size
                a ^= value
                b ^= value
                a = forward[a]
            a = backward[forward[a] ^ b]
            sector[destination+major] = a
            sector[destination+major+major_count] = a ^ b
    parity(86, 24, 2, 86, 2076)
    parity(52, 43, 86, 88, 2248)
    sector[12:16] = header
    return bytes(sector)


def main():
    source = ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin'
    cue_source = source.with_suffix('.cue')
    exe, location = disc_file(source, 'SCUS_942.49')
    patched = patch_executable(exe)
    lba = location['lba'] + OFFSET // 2048
    data_offset = 24 + OFFSET % 2048
    with source.open('rb') as stream:
        stream.seek(lba * 2352)
        original = stream.read(2352)
    normalized = encode_sector(original)
    if normalized[:2072] != original[:2072] or encode_sector(normalized) != normalized:
        raise ValueError('Encoder changes payload/header or is not idempotent')
    sector = bytearray(original)
    sector[data_offset:data_offset+4] = bytes(4)
    sector = encode_sector(sector)
    # Independent bitwise EDC verification (different implementation from lec.c).
    edc = 0
    for value in sector[16:2072]:
        edc ^= value
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
    if struct.unpack_from('<I', sector, 2072)[0] != edc:
        raise ValueError('Independent EDC check failed')
    if sector[:data_offset] != original[:data_offset] or sector[data_offset+4:2072] != original[data_offset+4:2072]:
        raise ValueError('Unexpected sector payload changes')
    target = OUT / 'TM3_TIMER_RECOVERY_V1.bin'
    cue = target.with_suffix('.cue')
    if target.exists() or cue.exists():
        raise FileExistsError('Candidate already exists; refusing overwrite')
    with source.open('rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    with target.open('r+b') as stream:
        stream.seek(lba * 2352)
        stream.write(sector)
    recovered, recovered_location = disc_file(target, 'SCUS_942.49')
    if recovered != patched or recovered_location != location:
        raise ValueError('Disc executable verification failed')
    # Prove unchanged raw bytes outside the one modified sector, including audio.
    with source.open('rb') as src, target.open('rb') as dst:
        offset = 0
        while old := src.read(1024*1024):
            new = dst.read(len(old))
            begin, end = lba*2352, (lba+1)*2352
            left, right = max(offset, begin), min(offset+len(old), end)
            if left < right:
                expected = bytearray(old)
                expected[left-offset:right-offset] = sector[left-begin:right-begin]
                assert new == expected
            else:
                assert new == old
            offset += len(old)
        assert not dst.read(1)
    cue_text = cue_source.read_text().replace(source.name, target.name)
    with cue.open('x', encoding='ascii', newline='') as stream:
        stream.write(cue_text)
    with (OUT / 'SCUS_942.49.timer_recovery_v1').open('xb') as stream:
        stream.write(patched)
    manifest = dict(status='experimental_gameplay_test_pending', pc=f'{PC:08X}',
                    old_word=f'{OLD:08X}', new_word='00000000', changed_lba=lba,
                    source=str(source), candidate=str(target), source_sha256=digest(source),
                    candidate_sha256=digest(target), executable_source_sha256=EXPECTED,
                    executable_candidate_sha256=hashlib.sha256(patched).hexdigest(),
                    single_sector_only=True, edc_ecc_rebuilt=True,
                    source_sector_edc_ecc_already_valid=(normalized == original),
                    packaged_files_untouched=True)
    with (OUT/'patch_manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
