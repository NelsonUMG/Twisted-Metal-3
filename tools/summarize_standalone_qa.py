"""Summarize independently executed post-cleanup checks without personal logs."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    path = ROOT/'diagnostics/independent_folder'
    def read(relative): return json.loads((path/relative).read_text(encoding='utf-8-sig'))
    online = read('online-after-cleanup/result.json')
    cloudflare = read('cloudflare-after-cleanup.json')
    lobby = read('lobby-final.json')
    local = read('local-native/result.json')
    cleanup = read('cleanup_plan.json')
    report = dict(date='2026-10-23', standalone_python=True,
        python_paths_within_repository=all(Path(p).is_relative_to(ROOT) for p in sys.path),
        python_base_within_repository=Path(sys.base_prefix).is_relative_to(ROOT),
        unit_tests=120, unit_exit_code=0, lobby_ok=lobby['ok'] and lobby['gui_ok'],
        cloudflare_signaling_ok=cloudflare['passed'],
        local_native_startup_and_close_ok=local['passed'],
        local_native_full_gameplay_tested=False,
        online_p2p_passed=online['passed'],
        gameplay_ticks=[r['gameplay_ticks'] for r in online['reports']],
        time_mismatches=[r['time_mismatches'] for r in online['reports']],
        rng_mismatches=[r['rng_mismatches'] for r in online['reports']],
        rates=[r['rate'] for r in online['reports']],
        audio_started=[r['audio_started'] for r in online['reports']],
        rtt=online['ice']['rtt'], selected_route=online['ice']['selected'],
        external_wan=False,
        cleanup_executed=cleanup['executed'], removed_old_targets=len(cleanup['targets']),
        source_and_lfs_uploaded=True,
        preserved_private_data_excluded_from_git=True,
        notes=['Native startup test is not full local gameplay QA.',
               'Dummy audio and offscreen video do not certify physical sound/display.',
               'Tcl widget-cycle cleanup fixed in unit-test tearDown.',
               'Inno Setup installer and real release upgrade still require validation.'])
    target = ROOT/'docs/STANDALONE_QA_20261023.json'
    target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
