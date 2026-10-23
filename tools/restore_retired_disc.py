"""Restore a retired BIN to a NEW destination, using its verified cleanup patch."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('patch', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--base', type=Path, default=Path(__file__).resolve().parent.parent /
                        'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin')
    args = parser.parse_args()
    with zipfile.ZipFile(args.patch) as archive:
        meta = json.loads(archive.read('metadata.json'))
        with args.base.open('rb') as base:
            assert hashlib.file_digest(base, 'sha256').hexdigest() == meta['base_sha256']
        names = set(archive.namelist())
        restored = hashlib.sha256()
        with args.destination.open('xb') as output, args.base.open('rb') as base:
            block = 0
            while data := base.read(meta['block_size']):
                member = f'blocks/{block}'
                if member in names:
                    data = archive.read(member)
                output.write(data)
                restored.update(data)
                block += 1
        assert restored.hexdigest() == meta['sha256'], 'Restored hash mismatch'
        print(f'Restored and verified: {args.destination}. CUE/XML sidecars are inside the patch ZIP.')

if __name__ == '__main__':
    main()
