"""Launch twice, reject duplicate, close owner, then verify the lock is reusable."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
CODE = f"import json,sys,time;sys.path.insert(0,r'{ROOT/'network'}');from lobby_entry import acquire_lobby_mutex;owned=acquire_lobby_mutex();open(sys.argv[1],'w').write(json.dumps({{'lock_acquired':owned}}));time.sleep(float(sys.argv[2])) if owned else None;sys.exit(0 if owned else 3)"


def main():
    with tempfile.TemporaryDirectory(prefix='tm3_singleton_qa_') as folder:
        base = Path(folder); first_file=base/'first.json'; second_file=base/'second.json'; third_file=base/'third.json'
        first = subprocess.Popen([sys.executable,'-c',CODE,str(first_file),'3'])
        try:
            deadline=time.monotonic()+10
            while not first_file.exists() and time.monotonic()<deadline: time.sleep(.05)
            assert first_file.exists() and json.loads(first_file.read_text())['lock_acquired']
            second=subprocess.run([sys.executable,'-c',CODE,str(second_file),'0'],timeout=10)
            assert second.returncode==3 and not json.loads(second_file.read_text())['lock_acquired']
        finally:
            first.wait(timeout=10)
        third=subprocess.run([sys.executable,'-c',CODE,str(third_file),'0'],timeout=10)
        assert third.returncode==0 and json.loads(third_file.read_text())['lock_acquired']
    print(json.dumps({'passed':True,'second_instance_blocked':True,
                      'lock_released_after_close':True,'mechanism':'Windows named mutex'}))


if __name__=='__main__': main()
