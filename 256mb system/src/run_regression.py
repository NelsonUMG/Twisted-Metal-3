"""Read-only regression of the unchanged working lobby, with saved evidence."""
import json
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent.parent
code="import gc,unittest;gc.disable();r=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('network',pattern='test_*.py'));raise SystemExit(not r.wasSuccessful())"
result=subprocess.run([sys.executable,'-c',code],cwd=BASE.parent,capture_output=True,text=True,timeout=90)
report=dict(exit_code=result.returncode,passed=result.returncode==0,
            stdout=result.stdout,stderr=result.stderr,production_files_modified=False)
(BASE/'reports/lobby_regression.json').write_text(json.dumps(report,indent=2))
print(result.stdout+result.stderr);raise SystemExit(result.returncode)
