"""Validate the complete portable after the clock / manual-wait correction."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / 'diagnostics/ice_p2p_v1'

def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest().upper()

path = ROOT / 'TM3Online_Portatil.zip'
prefix = 'TM3Online_UI2_175_20261021/'
with zipfile.ZipFile(path) as archive:
    assert archive.testzip() is None
    manifest = json.loads(archive.read(prefix + 'BUILD_MANIFEST.json'))
    assert manifest['p2p_update']['invitation_expiry_clock'] == 'monotonic_local'
    assert manifest['p2p_update']['invitation_lifetime_seconds'] == 1800
    for name in ('p2p_session.py', 'p2p_codes.py', 'p2p_window.py'):
        assert archive.read(prefix + 'sources/network/' + name) == (ROOT / 'network' / name).read_bytes()
    assert archive.read(prefix + 'TM3Lobby.exe') == (ROOT / 'TM3Online_Lobby/TM3Lobby.exe').read_bytes()
before = json.loads((QA / 'nat_tuning_before/BUILD_MANIFEST.json').read_text())
for entry in before['files']:
    if entry['file'].replace('\\', '/').startswith('runtime/'):
        assert digest(ROOT / 'TM3Online_Lobby' / entry['file']) == entry['sha256'].upper()
assert digest(ROOT / 'TM3Online_Lobby/TM3Lobby.json') == digest(QA / 'nat_tuning_before/TM3Lobby.json')
assert json.loads((QA / 'delayed_answer.json').read_text())['passed']
for name in ('frozen_probe.json', 'frozen_probe_patch.json'):
    result = json.loads((QA / name).read_text())
    assert result['passed'] and result['diagnostics']['clock_independent_expiry']
report = dict(passed=True, complete_zip_crc_valid=True, shipped_source_matches=True,
              runtime_and_personal_config_preserved=True, delayed_answer_seconds=80,
              lifetime_seconds=1800, sha256=digest(path), bytes=path.stat().st_size)
(QA / 'clock_release.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
