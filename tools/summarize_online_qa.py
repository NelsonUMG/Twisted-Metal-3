"""Publish small source-controlled evidence from isolated P2P QA outputs."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'network'))
from qa_role_order import validate

def main():
    evidence = dict(unit_tests_passed=120, external_wan=False, cases=[],
                    pending=['full_map_cycle_and_second_game', 'cancel_retry_real_menu',
                             'installer_execution',
                             'real_release_upgrade', 'physical_remote_audio'])
    for name in ('frozen_github_online', 'frozen_github_status_lock', 'retry_after_disconnect'):
        path = ROOT/'diagnostics'/name/'result.json'
        if not path.exists(): continue
        result = json.loads(path.read_text())
        evidence['cases'].append(dict(name=name, passed=result['passed'],
            ticks=[r['gameplay_ticks'] for r in result['reports']],
            rates=[r['rate'] for r in result['reports']],
            time_mismatches=[r['time_mismatches'] for r in result['reports']],
            rng_mismatches=[r['rng_mismatches'] for r in result['reports']],
            audio_started=[r['audio_started'] for r in result['reports']],
            selected_route=result['ice']['selected']))
    base = ROOT/'diagnostics/github_online_order_input_trace'
    for side, name in enumerate(('host_first', 'guest_first')):
        files = [base/name/f'report{i}.json' for i in (0, 1)]
        if not all(f.exists() for f in files): continue
        reports = [json.loads(f.read_text()) for f in files]
        passed = all(r['completed'] and r['gameplay_ticks'] == 600 and
                     r['time_mismatches'] == r['rng_mismatches'] == 0 for r in reports)
        check = validate(dict(passed=passed, reports=reports), side, 31)
        evidence['cases'].append(dict(name=name, validation=check,
                                     rates=[r['rate'] for r in reports]))
    for case in ('host_first', 'guest_first'):
        path = ROOT/'diagnostics/github_online_crossed'/case/'result.json'
        if path.exists():
            result = json.loads(path.read_text())
            side = 0 if case == 'host_first' else 1
            evidence['cases'].append(dict(name='crossed_'+case,
                validation=validate(result, side, 1, 1-side),
                rates=[r['rate'] for r in result['reports']]))
    path = ROOT/'diagnostics/github_online_disconnect/result.json'
    if path.exists():
        result = json.loads(path.read_text())
        evidence['cases'].append(dict(name='disconnect_during_real_waiting',
            passed=result['passed'], seconds_after_disconnect=result.get('seconds_after_disconnect'),
            exit_codes=result.get('exit_codes')))
    path = ROOT/'diagnostics/github_online_disconnect_frozen/result.json'
    if path.exists():
        result = json.loads(path.read_text())
        evidence['cases'].append(dict(name='frozen_disconnect_during_real_waiting',
            passed=result['passed'], seconds_after_disconnect=result.get('seconds_after_disconnect'),
            exit_codes=result.get('exit_codes')))
    output = ROOT/'docs/ONLINE_QA_20261023.json'
    output.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(evidence, indent=2))

if __name__ == '__main__': main()
