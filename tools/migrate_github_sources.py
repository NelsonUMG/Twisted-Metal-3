"""Copy source inputs into the user's new Git checkout; never copy game data."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '256mb system/Twisted-Metal-3'
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.wrangler', '.venv_lobby'}
SKIP_EXT = {'.o', '.obj', '.d', '.a', '.dll', '.exe', '.so', '.pdb', '.pyc', '.zip', '.bin', '.cue', '.iso', '.db', '.sqlite3', '.log'}

def copy_sources(source, target):
    for path in sorted(source.rglob('*')):
        rel = path.relative_to(source)
        if not path.is_file() or SKIP_DIRS.intersection(rel.parts) or path.suffix.lower() in SKIP_EXT:
            continue
        if path.name.startswith('.env') or path.name in {'wrangler.toml', 'wrangler.jsonc'}:
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)

def main():
    assert (DEST / '.git').is_dir()
    for source, target in [('network', 'network'), ('tools', 'tools'),
                           ('frontend/src', 'frontend/src'), ('frontend/include', 'frontend/include'),
                           ('256mb system/src', '256mb system/src'),
                           ('256mb system/core_source', '256mb system/core_source'),
                           ('diagnostics/vulkan_trial_20261022/source', 'cores/beetle-vulkan')]:
        if (ROOT / source).is_dir(): copy_sources(ROOT / source, DEST / target)
    for name in ('frontend/CMakeLists.txt', 'LICENSE', '256mb system/reports/reference.json'):
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    stable = ROOT / 'TM3Online_Jugar/TM3Online_UI2_175_20261021'
    for source, target in [('TM3Lobby.json', 'config/TM3Lobby.json'),
                           ('runtime/TM3Console.ini', 'config/TM3Console.example.ini')]:
        out = DEST / target; out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stable / source, out)
    # Old source archives may contain the only copy of the local frontend.
    import zipfile
    for name in ('console.zip', 'core_cpu175.zip'):
        with zipfile.ZipFile(stable / 'sources' / name) as archive:
            for info in archive.infolist():
                rel = Path(info.filename)
                if info.is_dir() or rel.is_absolute() or '..' in rel.parts or SKIP_DIRS.intersection(rel.parts) or rel.suffix.lower() in SKIP_EXT:
                    continue
                out = DEST / 'legacy-source' / name[:-4] / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, out.open('wb') as dst: shutil.copyfileobj(src, dst)
    records = {str(p.relative_to(DEST)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in DEST.rglob('*') if p.is_file() and '.git' not in p.relative_to(DEST).parts}
    (DEST / 'SOURCE_IMPORT.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(f'Imported {len(records)} source/configuration files into {DEST}')

if __name__ == '__main__': main()
