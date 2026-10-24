"""Produce content-addressed Release assets; no ZIP distribution."""
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'network'))
from file_updater import sha,validate_manifest

def build(payload, output, version):
    payload=Path(payload);output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    manifest=dict(schema=1,version='v'+version.lstrip('v'),files=[])
    for path in sorted(payload.rglob('*')):
        if not path.is_file():continue
        name=path.relative_to(payload).as_posix()
        if path.suffix.lower() in ('.msi','.msp','.msm','.wixpdb','.wixobj','.wixlib') or path.name.casefold() == 'tm3online-setup.exe':
            raise ValueError('Los instaladores son locales, no archivos de actualización: '+name)
        item=dict(path=name,size=path.stat().st_size,sha256=sha(path))
        manifest['files'].append(item)
    validate_manifest(manifest,payload)
    for item in manifest['files']:
        target=output/('tm3-'+item['sha256'])
        if not target.exists():shutil.copy2(payload/item['path'],target)
    (output/'TM3Online-update.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

if __name__=='__main__':
    build(ROOT/'build/payload', ROOT/'dist/update', (ROOT/'VERSION').read_text().strip())
