"""Startup/normal-close smoke test for the local native console, not gameplay QA."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    output = ROOT/'diagnostics/independent_folder/local-native'
    output.mkdir(parents=True, exist_ok=True)
    state = output/'state.json'
    runtime = ROOT/'runtime'
    process = subprocess.Popen([str(runtime/'TM3Online.exe'), '--windowed',
        '--core', str(runtime/'cores/beetle_psx_libretro.dll'),
        '--game', str(runtime/'game/TM3_SQRT_MERGE_V4.cue'),
        '--session-state', str(state), '--save-slot', 'independence_qa'], cwd=runtime)
    user = C.windll.user32
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    windows = []
    def collect(window, _):
        owner = W.DWORD(); user.GetWindowThreadProcessId(window, C.byref(owner))
        if owner.value == process.pid:
            title = C.create_unicode_buffer(2048); cls = C.create_unicode_buffer(256)
            user.GetWindowTextW(window, title, len(title)); user.GetClassNameW(window, cls, len(cls))
            windows.append((window, title.value, cls.value))
        return True
    callback = callback_type(collect)
    report = dict(passed=False, test='native local console startup and normal close; not full gameplay')
    try:
        started = time.monotonic()
        while time.monotonic() - started < 10 and process.poll() is None: time.sleep(.1)
        user.EnumWindows(callback, 0)
        main_windows = [w for w in windows if w[2] == 'TM3OnlineWindow']
        report.update(alive_after_10_seconds=process.poll() is None,
                      titles=[w[1] for w in windows],
                      error_dialog=any(w[2] == '#32770' for w in windows))
        for window, *_ in main_windows: user.PostMessageW(window, 0x10, 0, 0)
        try: process.wait(10)
        except subprocess.TimeoutExpired: pass
        report.update(exit_code=process.poll(),
                      state=json.loads(state.read_text()) if state.exists() else None)
        report['passed'] = bool(report['alive_after_10_seconds'] and main_windows and
                                not report['error_dialog'] and process.poll() == 0)
    finally:
        if process.poll() is None: process.terminate(); process.wait(5)
    (output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)

if __name__ == '__main__': main()
