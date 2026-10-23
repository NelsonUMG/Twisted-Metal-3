"""Replace only the lobby and changed sources, preserving the current assets."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile
from datetime import datetime

root = Path(__file__).resolve().parent.parent
archive = root / 'TM3Online_Portatil.zip'
prefix = 'TM3Online_UI2_175_20261021/'
exe = root / 'diagnostics/system256_cable_p2p_qa/frozen/dist/TM3Lobby_P2P.exe'
backup = root / ('TM3Online_Portatil_BACKUP_WAITING_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.zip')
replacement = {prefix + 'TM3Lobby.exe': exe.read_bytes()}
for name in ('system256_runtime.py', 'system256_peer_cable.py', 'lobby_client.py'):
    replacement[prefix + 'sources/network/' + name] = (root / 'network' / name).read_bytes()
with zipfile.ZipFile(archive) as old:
    assets = {}
    for name in old.namelist():
        if name.startswith(prefix + 'runtime/system256/') and not name.endswith('/'):
            with old.open(name) as stream:
                assets[name.rsplit('/', 1)[1]] = hashlib.file_digest(stream, 'sha256').hexdigest()
    replacement[prefix + 'RELEASE_FILES.json'] = json.dumps(dict(system256=assets), indent=2).encode()
    manifest = json.loads(old.read(prefix + 'BUILD_MANIFEST.json'))
    for name, content in replacement.items():
        relative = name[len(prefix):].replace('/', '\\')
        entry = next((e for e in manifest.get('files', []) if e['file'] == relative), None)
        if entry is None:
            entry = {'file': relative}
            manifest.setdefault('files', []).append(entry)
        entry.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest['waiting_release'] = dict(timeout_seconds=None, native_role_wait=True,
        cable_exchange_timeout_seconds=30,
        activity_window_seconds=120, requires_same_version_on_both_peers=True,
        persistent_error_log=True, cross_isp_gameplay_validated=False)
    replacement[prefix + 'BUILD_MANIFEST.json'] = json.dumps(manifest, indent=2).encode()
    shutil.copy2(archive, backup)
    temporary = archive.with_suffix('.waiting.tmp.zip')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            if info.filename not in replacement:
                with old.open(info) as source, new.open(info, 'w') as target:
                    shutil.copyfileobj(source, target)
        for name, content in replacement.items():
            new.writestr(name, content)
with zipfile.ZipFile(temporary) as checked:
    assert checked.testzip() is None
    assert len(checked.namelist()) == len(set(checked.namelist()))
    for name, content in replacement.items():
        assert checked.read(name) == content
temporary.replace(archive)
print(json.dumps(dict(archive=str(archive), backup=str(backup), integrity=True)))
