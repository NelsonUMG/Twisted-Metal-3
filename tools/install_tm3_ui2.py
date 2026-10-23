"""Install verified UI2 files, preserving existing saves, BIOS and preferences."""
from pathlib import Path
import json
import shutil
from package_tm3_semiproduction import digest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'dist/TM3Online_UI2_175_20261021'
TARGET = ROOT / 'TM3Online_Lobby'
BACKUP = ROOT / 'diagnostics/console_v2_previous/installed_files'

def main():
    manifest = json.loads((SOURCE / 'BUILD_MANIFEST.json').read_text())
    for item in manifest['files']:
        assert digest(SOURCE / item['file']) == item['sha256']
    BACKUP.mkdir(parents=True, exist_ok=False)
    for source in SOURCE.rglob('*'):
        if not source.is_file():
            continue
        relative = source.relative_to(SOURCE)
        target = TARGET / relative
        if target.exists() and digest(target) == digest(source):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = BACKUP / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            # Windows permits renaming a running frozen server's image. Its existing
            # session keeps running; the next launch uses the updated executable.
            target.rename(backup)
        shutil.copy2(source, target)
    for item in manifest['files']:
        assert digest(TARGET / item['file']) == item['sha256']
    print('UI2 installed and hashes verified; personal files untouched.')

if __name__ == '__main__':
    main()
