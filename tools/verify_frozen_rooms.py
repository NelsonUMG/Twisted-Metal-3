"""Installed / update EXE talks to the real local Worker without Python PATH."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    node = subprocess.Popen(['node.exe', str(ROOT / 'network/cloudflare/lab.mjs')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    process = None
    try:
        url = json.loads(node.stdout.readline())['url'].rstrip('/')
        with tempfile.TemporaryDirectory(prefix='tm3_frozen_rooms_') as folder:
            folder = Path(folder)
            executable = ROOT / 'TM3Online_Lobby/TM3Lobby.exe'
            if '--patch' in sys.argv:
                with zipfile.ZipFile(ROOT / 'TM3Online_Actualizacion_Salas.zip') as archive:
                    assert 'TM3Lobby.json' not in archive.namelist()
                    archive.extractall(folder / 'app')
                executable = folder / 'app/TM3Lobby.exe'
            report = folder / 'report.json'
            environment = {**os.environ, 'PATH': str(Path(os.environ['SystemRoot']) / 'System32'), 'LOCALAPPDATA': str(folder)}
            process = subprocess.Popen([str(executable), '--check-directory', url, str(report)], env=environment)
            assert process.wait(timeout=45) == 0, report.read_text() if report.exists() else 'Frozen room check failed'
            result = json.loads(report.read_text())
            assert result['passed'] and result['frozen'] and result['automatic_worker_signaling']
            assert result['manual_codes_used'] is False and result['native_controls_and_datagrams']
            assert result['peer_ping_measured']
            result.update(real_cloudflare_deployment=False, real_wan_test=False)
            name = 'frozen_patch.json' if '--patch' in sys.argv else 'frozen_installed.json'
            (ROOT / 'diagnostics/rooms_auto_v1' / name).write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
    finally:
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        if node.poll() is None:
            node.stdin.write('stop\n'); node.stdin.flush()
            try:
                node.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                node.terminate(); node.wait(timeout=3)


if __name__ == '__main__':
    main()
