"""Check NAT test evidence, delivered hashes and preserved runtime/config."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / 'diagnostics/ice_p2p_v1'
INSTALLED = ROOT / 'TM3Online_Lobby'


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest().upper()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    simulation = read(QA / 'nat_simulation.json')
    assert simulation['passed'] and len(simulation['scenarios']) == 6
    assert not simulation['real_wan_test'] and not simulation['real_hotspot_test']
    assert all(case['passed'] and case['cleanup_threads_stopped'] for case in simulation['scenarios'])
    high_latency = read(QA / 'nat_simulation_20261022T180509225717Z.json')
    assert high_latency['passed'] and len(high_latency['scenarios']) == 3
    assert all(case['scenario'] == 'mobile_latency' and case['passed'] for case in high_latency['scenarios'])
    gui = read(QA / 'lobby_nat_check.json')
    assert all(gui[key] for key in ('simulated_nat', 'actual_emulators_connected',
        'cancel_preserves_transport', 'second_start_new_generation', 'owned_processes_closed'))
    for name in ('frozen_probe.json', 'frozen_probe_patch.json'):
        result = read(QA / name)
        assert result['passed'] and 'coalesced' in result['diagnostics']
    assert read(QA / 'frozen_lobby.json')['manifest_verified']
    before = read(QA / 'nat_tuning_before/BUILD_MANIFEST.json')
    unchanged = []
    for entry in before['files']:
        if entry['file'].replace('\\', '/').startswith('runtime/'):
            assert digest(INSTALLED / entry['file']) == entry['sha256'].upper(), entry['file']
            unchanged.append(entry['file'])
    assert digest(INSTALLED / 'TM3Lobby.json') == digest(QA / 'nat_tuning_before/TM3Lobby.json')
    assert digest(INSTALLED / 'sources/network/p2p_session.py') == digest(ROOT / 'network/p2p_session.py')
    manifest = read(INSTALLED / 'BUILD_MANIFEST.json')
    assert manifest['p2p_update']['game_flow_control'] == 'bounded_retry_coalescing_v1'
    assert not manifest['p2p_update']['mobile_hotspot_validated']
    artifacts = {}
    for name in ('TM3Online_Portatil.zip', 'TM3Online_Actualizacion_P2P.zip'):
        path = ROOT / name
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            if 'Actualizacion' in name:
                assert 'TM3Lobby.json' not in archive.namelist()
                assert 'SIMULACION_NAT_ES.md' in archive.namelist()
                assert hashlib.sha256(archive.read('TM3Lobby.exe')).hexdigest().upper() == digest(INSTALLED / 'TM3Lobby.exe')
        artifacts[name] = dict(bytes=path.stat().st_size, sha256=digest(path))
    report = dict(passed=True, nat_cases_passed=6, high_latency_repetitions_passed=3,
                  gui_with_real_emulators_passed=True, frozen_installed_and_patch_passed=True,
                  personal_lobby_config_unchanged=True, runtime_files_unchanged=unchanged,
                  real_wan_validated=False, real_hotspot_validated=False, artifacts=artifacts)
    (QA / 'nat_release_check.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
