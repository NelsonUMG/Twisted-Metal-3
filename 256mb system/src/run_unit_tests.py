import io
import json
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parent.parent
suite=unittest.defaultTestLoader.discover(str(BASE/'src'),pattern='test_*.py')
output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
report=dict(tests_run=result.testsRun,passed=result.wasSuccessful(),failures=len(result.failures),
            errors=len(result.errors),output=output.getvalue())
(BASE/'reports/unit_tests.json').write_text(json.dumps(report,indent=2))
print(output.getvalue());raise SystemExit(0 if result.wasSuccessful() else 1)
