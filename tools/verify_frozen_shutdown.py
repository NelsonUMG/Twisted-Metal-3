"""Verify that closing the frozen lobby leaves neither its game nor server alive."""
from pathlib import Path
import json
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent

def main():
    with tempfile.TemporaryDirectory(prefix='tm3_shutdown_qa_') as directory:
        report = Path(directory) / 'shutdown.json'
        environment = {**os.environ, 'LOCALAPPDATA': directory}
        process = subprocess.Popen([str(ROOT / 'TM3Online_Lobby/TM3Lobby.exe'), '--check-shutdown', str(report)], env=environment)
        try:
            assert process.wait(timeout=30) == 0, 'Frozen shutdown check failed'
            result = json.loads(report.read_text())
            assert result['game_exited'] and result['directory_threads_stopped'] and result['frozen']
            target = ROOT / 'diagnostics/session_rules_v3/frozen_shutdown.json'
            target.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process.wait(timeout=5)

if __name__ == '__main__': main()
