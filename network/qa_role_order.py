"""Real-menu two-process QA for asymmetric YES and later menu confirmations."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import time

from system256_cable_p2p_qa import run, DEFAULT_ASSETS, DEFAULT_SETTINGS, DEFAULT_FIXTURE


ROOT = Path(__file__).resolve().parents[1]
YES_FRAME = 2024
YES_RELEASE = 2039


def insert_pause(recording, frame, frames):
    return recording[:frame] + [0] * frames + recording[frame:]


def make_fixture(first_side, wait_frames, output, crossed=False):
    fixture = json.loads(DEFAULT_FIXTURE.read_text())
    other = 1 - first_side
    # The first console performs its recorded YES press and then remains idle;
    # the other remains idle before that exact recorded YES press.  Thus later
    # menu input is not consumed behind the game's native WAITING screen.
    fixture['input_recording'][first_side] = insert_pause(
        fixture['input_recording'][first_side], YES_RELEASE, wait_frames)
    fixture['input_recording'][other] = insert_pause(
        fixture['input_recording'][other], YES_FRAME, wait_frames)
    selection_first = 1 - first_side if crossed else first_side
    selection_delay_frames = 600 if selection_first == 0 else 0
    if selection_delay_frames:
        # Side 1 reaches the following selection sooner in the reference path.
        # Hold it after YES so side 0's next native menu confirmation is first.
        fixture['input_recording'][1] = insert_pause(
            fixture['input_recording'][1], YES_RELEASE + wait_frames,
            selection_delay_frames)
    fixture['qa_role_order'] = dict(first_side=first_side, wait_frames=wait_frames,
                                    yes_frame=YES_FRAME, yes_release=YES_RELEASE,
                                    selection_delay_frames=selection_delay_frames)
    output.write_text(json.dumps(fixture), encoding='utf-8')


def validate(result, first_side, minimum_wait, selection_first=None):
    if selection_first is None: selection_first = first_side
    reports = result['reports']
    local = [[e for e in report['role_events'] if e['event'] == 'local_yes'][0]
             for report in reports]
    completed = [[e for e in report['role_events'] if e['event'] == 'role_completed'][0]
                 for report in reports]
    order_ok = local[first_side]['monotonic'] < local[1-first_side]['monotonic']
    waited = completed[first_side]['wait_seconds']
    reused = [[e for e in report['role_events'] if e['event'] == 'role_reused']
              for report in reports]
    confirms = [[e for e in report.get('input_events', [])
                 if e['menu'] == '0x80080494' and e['mask'] & 1]
                for report in reports]
    selection_order_ok = (confirms[selection_first] and confirms[1-selection_first] and
                         confirms[selection_first][0]['monotonic'] < confirms[1-selection_first][0]['monotonic'])
    return dict(order_ok=order_ok, first_side=first_side,
                first_role=2 if first_side == 0 else 1,
                local_yes=local, completed=completed, wait_seconds=waited,
                over_minimum=waited >= minimum_wait, first_reused=reused,
                selection_confirm_inputs=confirms,
                selection_first=selection_first,
                selection_order_ok=bool(selection_order_ok),
                passed=result['passed'] and order_ok and waited >= minimum_wait and selection_order_ok)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--wait-frames', type=int, default=2100)
    parser.add_argument('--minimum-wait', type=float, default=31.0)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--assets', default=str(DEFAULT_ASSETS))
    parser.add_argument('--settings', default=str(DEFAULT_SETTINGS))
    parser.add_argument('--frozen-exe')
    parser.add_argument('--crossed', action='store_true')
    args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    results = []
    for first_side in (0, 1):
        case = output / ('host_first' if first_side == 0 else 'guest_first')
        case.mkdir()
        fixture = case / 'fixture.json'
        make_fixture(first_side, args.wait_frames, fixture, args.crossed)
        try:
            result = run(SimpleNamespace(output=str(case), assets=args.assets,
                settings=args.settings, fixture=str(fixture), frozen_exe=args.frozen_exe,
                timeout=args.timeout))
            validation = validate(result, first_side, args.minimum_wait,
                                  1-first_side if args.crossed else first_side)
            results.append(dict(case=case.name, validation=validation,
                                reports=result['reports'], ice=result['ice']))
        except Exception as exc:
            results.append(dict(case=case.name, validation=dict(passed=False), error=repr(exc)))
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results[-1]), flush=True)
    raise SystemExit(0 if all(r['validation']['passed'] for r in results) else 1)


if __name__ == '__main__':
    main()
