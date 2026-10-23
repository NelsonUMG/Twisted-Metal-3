"""Functional ICE check of the portable EXE with Python absent from PATH."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory(prefix='tm3_frozen_ice_') as folder:
        report = Path(folder)/'report.json'
        environment = {**os.environ, 'PATH': str(Path(os.environ['SystemRoot'])/'System32'), 'LOCALAPPDATA': folder}
        executable = ROOT/'TM3Online_Lobby/TM3Lobby.exe'
        patch_check = '--patch' in sys.argv
        if patch_check:
            app = Path(folder)/'app'
            with zipfile.ZipFile(ROOT/'TM3Online_Actualizacion_P2P.zip') as archive:
                assert archive.testzip() is None
                assert 'TM3Lobby.json' not in archive.namelist()
                archive.extractall(app)
            executable = app/'TM3Lobby.exe'
        process = subprocess.Popen([str(executable), '--check-ice', str(report)], env=environment)
        try:
            assert process.wait(timeout=40) == 0, 'Frozen ICE check failed'
            result = json.loads(report.read_text())
            assert result['passed'] and result['frozen'] and result['encrypted']
            assert result['datagrams_both_directions'] and result['cancel_keeps_transport']
            assert {'coalesced', 'expired', 'pending'} <= result['diagnostics'].keys(), 'Outdated launcher: game flow-control counters missing'
            assert result['diagnostics']['pending'] <= 256
            assert result['diagnostics'].get('clock_independent_expiry') is True
            result['artifact'] = 'patch_zip' if patch_check else 'installed'
            destination = ROOT/'diagnostics/ice_p2p_v1'/('frozen_probe_patch.json' if patch_check else 'frozen_probe.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
