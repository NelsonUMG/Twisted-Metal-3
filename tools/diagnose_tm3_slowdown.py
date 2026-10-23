"""Read-only, prospective TM3 slowdown capture. No game or process writes."""
import argparse
import csv
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import statistics
import struct
import time

from analyze_tm3_link_wait import records, summarize

CORE_HASH = 'CCAA89C96946E87959249287067D09F124D04F476652ADC4C75CAF0C3FA1C082'
CORE_RAM_RVAS = {
    CORE_HASH: 0xA07A10,
    # Base core: nm MainRAM=225F959D0, PE ImageBase=225590000.
    # retro_get_memory_data(2) disassembly confirms pointer-to-wrapper layout.
    '1E057FFAE609E633AA4D371B561F41BD94109FC557EFB1758D760CBE9138F0C9': 0xA059D0,
}
FIELDS = dict(local_humans=0xD2CB0, remote_humans=0xD2CB4, cpu_config=0xD2CBC,
              total_config=0xD2CC0, map=0xD2CC4, pause=0xD2D3C, state=0xD2D40,
              request=0xD2D44, sync_error=0xD2D50, variant=0xD2D54,
              active_total=0xD3234, role=0xD3298, game_time=0x895A8)


def utc():
    return datetime.now(timezone.utc).isoformat()


def prefix(path):
    raw = path.read_bytes()
    return raw[:raw.rfind(b'\n') + 1]


def perf_rows(raw):
    return [{k: float(v) for k, v in row.items()} for row in
            csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
            if None not in row and all(v is not None for v in row.values())]


class Reader:
    """Only QUERY_INFORMATION | VM_READ handles; pinned module layout."""
    def __init__(self, pid, executable, core):
        core_hash = hashlib.sha256(core.read_bytes()).hexdigest().upper()
        if core_hash not in CORE_RAM_RVAS:
            raise RuntimeError('Unsupported core hash: RAM sampling refused')
        self.ram_rva = CORE_RAM_RVAS[core_hash]
        if C.sizeof(C.c_void_p) != 8:
            raise RuntimeError('Use 64-bit Python')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.p = C.WinDLL('psapi', use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.p.EnumProcessModules.argtypes = [W.HANDLE, C.POINTER(C.c_void_p), W.DWORD, C.POINTER(W.DWORD)]
        self.p.GetModuleFileNameExW.argtypes = [W.HANDLE, C.c_void_p, W.LPWSTR, W.DWORD]
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        try:
            name, length = C.create_unicode_buffer(32768), W.DWORD(32768)
            if not self.k.QueryFullProcessImageNameW(self.handle, 0, name, C.byref(length)):
                raise C.WinError(C.get_last_error())
            if Path(name.value).resolve() != Path(executable).resolve():
                raise RuntimeError('PID executable differs from TEST_CONTEXT')
            modules, needed = (C.c_void_p * 1024)(), W.DWORD()
            if not self.p.EnumProcessModules(self.handle, modules, C.sizeof(modules), C.byref(needed)):
                raise C.WinError(C.get_last_error())
            if needed.value > C.sizeof(modules):
                raise RuntimeError('Module list truncated')
            self.base = None
            for module in modules[:needed.value // C.sizeof(C.c_void_p)]:
                if self.p.GetModuleFileNameExW(self.handle, module, name, len(name)):
                    if Path(name.value).resolve() == core.resolve():
                        self.base = module
            if self.base is None:
                raise RuntimeError('Expected core is not loaded')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        buf, count = C.create_string_buffer(size), C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, address, buf, size, C.byref(count)) or count.value != size:
            raise C.WinError(C.get_last_error())
        return buf.raw

    def sample(self):
        started = time.monotonic()
        wrapper, = struct.unpack('<Q', self.read(self.base + self.ram_rva, 8))
        data, size = struct.unpack('<QI', self.read(wrapper, 12))
        if size != 0x1000000 or not data:
            raise RuntimeError('Unexpected MainRAM layout')
        # One contiguous read for state fields, plus TIME. Not an atomic snapshot.
        block = self.read(data + 0xD2CB0, 0xD329C - 0xD2CB0)
        out = {k: struct.unpack_from('<I', block, offset - 0xD2CB0)[0]
               for k, offset in FIELDS.items() if k != 'game_time'}
        out['game_time'], = struct.unpack('<I', self.read(data + FIELDS['game_time'], 4))
        times = [W.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(self.handle, *(C.byref(t) for t in times)):
            raise C.WinError(C.get_last_error())
        out['cpu_seconds'] = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 1e7
        out.update(captured_utc=utc(), monotonic_s=time.monotonic(), read_duration_ms=(time.monotonic()-started)*1000)
        return out


def analyze(perf, trace, start_elapsed, end_elapsed):
    rows = perf_rows(perf)
    chosen = [r for r in rows if start_elapsed < r['elapsed_s'] <= end_elapsed]
    before = [r for r in rows if r['elapsed_s'] <= start_elapsed]
    if not chosen or not before:
        return {'valid': False, 'reason': 'No complete prospective window'}
    first, last = int(before[-1]['completed_total']) + 1, int(chosen[-1]['completed_total'])
    parsed = records(trace.decode('utf-8-sig', errors='replace'))
    matched = [r for r in parsed if first <= int(r.get('seq', -1)) <= last]
    seqs = [int(r['seq']) for r in matched]
    complete = last >= first and len(seqs) == last-first+1 and len(set(seqs)) == len(seqs)
    gameplay = [r for r in matched if r.get('call') == '8003AA98']
    wall = sum(r['window_s'] for r in chosen)
    frames = sum(r['core_frames'] for r in chosen)
    steps = sum(r['time_steps'] for r in chosen)
    # Exact host-observed decomposition, NOT peer compute time or wire RTT.
    pre = [max(0, r['ready_us']-r['observed_us']) / 1000 for r in gameplay]
    post = [max(0, r['wait_us']/1000 - a) for r, a in zip(gameplay, pre)]
    mismatch = [r for r in matched if 'MISMATCH' in r.get('sync', '')]
    discontinuities = sum(r['time_discontinuities'] for r in chosen)
    return dict(valid=complete and not mismatch and not discontinuities and len(gameplay)==len(matched),
                sequence_first=first, sequence_last=last, trace_coverage_complete=complete,
                matched_records=len(matched), gameplay_records=len(gameplay), mismatches=len(mismatch),
                time_discontinuities=discontinuities, sampled_wall_s=wall,
                elapsed_start=before[-1]['elapsed_s'], elapsed_end=chosen[-1]['elapsed_s'],
                core_calls_per_s=frames/wall, time_units_per_s=steps/wall,
                core_calls_per_time_unit=frames/steps if steps else None,
                core_ms_per_wall_second=sum(r['core_ms_mean']*r['core_frames'] for r in chosen)/wall,
                paint_ms_per_wall_second=sum(r['paint_ms'] for r in chosen)/wall,
                core_ms_max=max(r['core_ms_max'] for r in chosen),
                waits=summarize(gameplay),
                before_remote_available_ms_mean=statistics.mean(pre) if pre else None,
                after_both_available_ms_mean=statistics.mean(post) if post else None)


def capture(run, seconds, interval, output):
    context = json.loads((run/'TEST_CONTEXT.json').read_text(encoding='utf-8-sig'))
    core = run/'cores/beetle_psx_libretro.dll'
    if hashlib.sha256(core.read_bytes()).hexdigest().upper() not in CORE_RAM_RVAS:
        raise RuntimeError('Unsupported core hash: RAM sampling refused')
    output.mkdir(parents=True, exist_ok=False)
    (output/'TEST_CONTEXT.json').write_bytes((run/'TEST_CONTEXT.json').read_bytes())
    readers, samples, starts, ends = {}, [], {}, {}
    try:
        for p in context['processes']:
            readers[p['side']] = Reader(p['pid'], p['executable'], core)
        if set(readers) != {'Oscar', 'Sofia'}:
            raise RuntimeError('Expected exactly Oscar and Sofia')
        for side in readers:
            starts[side] = perf_rows(prefix(run/f'{side.lower()}.host_performance.csv'))[-1]['elapsed_s']
        deadline = time.monotonic() + seconds
        with (output/'samples.jsonl').open('x', encoding='utf-8') as stream:
            while True:
                sample = {side: reader.sample() for side, reader in readers.items()}
                samples.append(sample)
                stream.write(json.dumps(sample)+'\n')
                stream.flush()
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(interval, max(0, deadline-time.monotonic())))
        for side in readers:
            ends[side] = perf_rows(prefix(run/f'{side.lower()}.host_performance.csv'))[-1]['elapsed_s']
        # Allow buffered trace writes to catch up to fixed CSV boundaries.
        time.sleep(2)
        result = dict(schema='tm3_slowdown_diagnostic_v1', captured_utc=utc(), run=str(run), sides={})
        for side in readers:
            sources = {}
            for filename in (f'{side.lower()}.host_performance.csv', f'TM3Online_{side}.rngcaller.trace.log'):
                raw = prefix(run/filename)
                (output/filename).write_bytes(raw)
                sources[filename] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            perf = (output/f'{side.lower()}.host_performance.csv').read_bytes()
            trace = (output/f'TM3Online_{side}.rngcaller.trace.log').read_bytes()
            analysis = analyze(perf, trace, starts[side], ends[side])
            series = [s[side] for s in samples]
            states = {key: sorted({s[key] for s in series}) for key in FIELDS if key != 'game_time'}
            stable = all(len(states[k]) == 1 for k in ('active_total', 'map', 'state', 'role', 'total_config', 'cpu_config', 'local_humans', 'remote_humans', 'variant'))
            stable = stable and states['pause']==[0] and states['state']==[3] and states['request']==[0] and states['sync_error']==[0]
            analysis.update(sources=sources, sampled_states=states, population_and_scene_stable_in_samples=stable,
                            cpu_core_equivalents=(series[-1]['cpu_seconds']-series[0]['cpu_seconds'])/(series[-1]['monotonic_s']-series[0]['monotonic_s']))
            analysis['usable_for_comparison'] = analysis['valid'] and stable and analysis.get('sampled_wall_s', 0) >= 30
            result['sides'][side] = analysis
        result['assessment'] = {
            'root_cause_proven': False,
            'comparable_30s_windows': all(s['usable_for_comparison'] for s in result['sides'].values()),
            'next_measurement': 'Compare identical map and active population. To isolate BIN functions, instrument guest publication, resume and simulation phases in a new core run.',
            'evidence': []}
        for side, s in result['sides'].items():
            evidence = result['assessment']['evidence']
            if not s['usable_for_comparison']:
                evidence.append(f'{side}: insufficient duration, changed scene/population, or incomplete/invalid trace; inspect validity fields.')
            if s.get('before_remote_available_ms_mean') is not None:
                a, b = s['before_remote_available_ms_mean'], s['after_both_available_ms_mean']
                evidence.append(f'{side}: {a:.3f} ms before remote availability; {b:.3f} ms afterwards. These observations do not separate peer compute from scheduling/transport.')
            if s.get('core_calls_per_s', 0) >= 59:
                evidence.append(f'{side}: core cadence near 60/s; this does not exclude expensive guest work or identify visible FPS.')
        result['limitations'] = [
            'TIME units are not unique visible FPS. No automatic root-cause verdict.',
            'RAM sampled periodically, sequentially, not atomically; changes between samples may be missed.',
            'CSV boundary may precede first RAM sample by about one reporting interval.',
            'Before remote available includes peer readiness, scheduling and transport. After available is host processing, not guest resume.',
            'Worker gap maximum is not an additive latency component. Retries are not proof of packet loss.',
            'Core wall time includes emulation and scheduling, not isolated AI/physics/render cost.',
            'Exact guest publication/resume and function costs require additional core instrumentation.',
            'Saved prefixes allow reanalysis; missing trace records invalidate coverage, including trace cap/buffering.'
        ]
        (output/'report.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        for reader in readers.values():
            reader.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    if args.seconds < 2 or not 0.1 <= args.interval <= args.seconds:
        p.error('seconds >= 2 and 0.1 <= interval <= seconds required')
    out = args.output or args.run/('slowdown_diagnostic_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    capture(args.run.resolve(), args.seconds, args.interval, out.resolve())
