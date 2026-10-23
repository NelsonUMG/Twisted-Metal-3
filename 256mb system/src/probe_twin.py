"""Owned headless two-console integration, not a real WAN gameplay test."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from twin_core import Core, LocalCable

BASE = Path(__file__).resolve().parent.parent


def scripted(side, frame):
    # Real controller events, not patched menu/world/TIME values.
    phase = frame % 120
    return ((1 << 3 if phase < 12 else (1 if 45 <= phase < 60 else 0)), 0)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=int, default=4800)
    p.add_argument('--seconds', type=float, default=90)
    p.add_argument('--paced', action='store_true')
    args = p.parse_args()
    os.environ.update(TM3O_STANDARD_PS1='0', TM3O_DIAGNOSTICS='0')
    cable = LocalCable(); cores = []; errors = []; threads = []
    menu_entered = [(-1, 0), (-1, 0)]
    def automated(side, frame):
        menu = cores[side].word(0x89a0c)
        previous, since = menu_entered[side]
        if previous != menu:
            since = frame; menu_entered[side] = (menu, since)
        age = frame - since
        if cable.gameplay > 10: return (1, 0)
        if menu == 0x8007ffe8:
            return ((1 << 4 if 10 <= age < 20 else (1 if age % 120 in range(40,55) else 0)), 0)
        return scripted(side, frame)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='tm3_twin_') as folder:
        try:
            for side in (0,1):
                cores.append(Core(BASE/'core_source/mednafen_psx_libretro.dll',
                                  BASE/'game/TM3_SYSTEM256.cue', Path(folder)/str(side), side, cable, automated))
            started = time.perf_counter()
            def run(core):
                try:
                    while core.frame < args.frames and not cable.stopped:
                        core.step()
                        if args.paced:
                            wait = started + core.frame / 59.94 - time.perf_counter()
                            if wait > 0: time.sleep(wait)
                except BaseException as exc:
                    errors.append(repr(exc)); cable.stop()
            threads = [threading.Thread(target=run, args=(c,), daemon=True) for c in cores]
            for t in threads: t.start()
            rows = []
            while any(t.is_alive() for t in threads) and time.perf_counter()-started < args.seconds:
                time.sleep(2)
                row = dict(elapsed_s=time.perf_counter()-started,
                           consoles=[dict(frame=c.frame, menu=hex(c.word(0x89a0c)), time=c.word(0x895a8),
                                          role=c.word(0xd3298), flags=hex(c.word(0x47908)),
                                          input_calls=c.input_calls, pressed_calls=c.pressed_calls,
                                          mailbox=hex(c.word(0x47904))) for c in cores],
                           exchanges=cable.exchanges, gameplay=cable.gameplay,
                           time_mismatches=cable.time_mismatches, rng_mismatches=cable.rng_mismatches,
                           error=cable.error)
                rows.append(row); print(json.dumps(row), flush=True)
                for c in cores: c.screenshot(BASE/f'reports/console_{c.side}.bmp')
            cable.stop()
            for t in threads: t.join(12)
            assert not any(t.is_alive() for t in threads), 'Owned core thread did not exit'
            report = dict(kind='real_twin_console_integration', rows=rows, errors=errors,
                          cable_error=cable.error, transitions=[c.transitions for c in cores],
                          actual_wan=False, gameplay_tested=cable.gameplay>0)
            (BASE/'reports/twin_probe.json').write_text(json.dumps(report,indent=2))
        finally:
            cable.stop()
            for t in threads: t.join(12)
            for c in cores: c.close()


if __name__ == '__main__': main()
