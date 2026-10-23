"""Isolated real-core checkpoint/replay probe. Does NOT prove linked gameplay."""
import ctypes as C
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import struct

ROOT = Path(__file__).resolve().parent.parent


class Game(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=ROOT / 'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll')
    parser.add_argument('--content', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'diagnostics/internet_engine_v1/core_checkpoint.json')
    parser.add_argument('--ram256', action='store_true')
    parser.add_argument('--check-guest', action='store_true')
    parser.add_argument('--enter-guest', action='store_true', help='Use the isolated core QA entry hook, not BIOS boot')
    args = parser.parse_args()
    os.environ['TM3O_STANDARD_PS1'] = '0'
    os.environ['TM3O_DIAGNOSTICS'] = '0'
    core = C.CDLL(str(args.core.resolve()))
    with tempfile.TemporaryDirectory(prefix='tm3_checkpoint_') as folder:
        directory = str(Path(folder)).encode()
        @C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
        def environment(command, data):
            if command in (9, 30, 31):
                C.cast(data, C.POINTER(C.c_char_p))[0] = directory
                return True
            if command == 3:
                C.cast(data, C.POINTER(C.c_bool))[0] = True
                return True
            if command == 17:
                C.cast(data, C.POINTER(C.c_bool))[0] = False
                return True
            if command == 44:
                # Negotiate the core's variable-size serialization contract.
                C.cast(data, C.POINTER(C.c_uint64))[0] |= 1 << 3
                return True
            return command in (8, 10, 11, 13, 16, 18, 32, 35, 36, 37)
        @C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
        def video(data, width, height, pitch): pass
        @C.CFUNCTYPE(None, C.c_int16, C.c_int16)
        def audio(left, right): pass
        @C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
        def batch(data, frames): return frames
        @C.CFUNCTYPE(None)
        def poll(): pass
        @C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
        def input_state(port, device, index, button): return 0
        for name, callback in (('environment', environment), ('video_refresh', video),
                               ('audio_sample', audio), ('audio_sample_batch', batch),
                               ('input_poll', poll), ('input_state', input_state)):
            fn = getattr(core, 'retro_set_' + name)
            fn.argtypes = [type(callback)]
            fn(callback)
        core.retro_load_game.argtypes = [C.POINTER(Game)]
        core.retro_load_game.restype = C.c_bool
        core.retro_serialize_size.restype = C.c_size_t
        for name in ('retro_serialize', 'retro_unserialize'):
            fn = getattr(core, name)
            fn.argtypes = [C.c_void_p, C.c_size_t]
            fn.restype = C.c_bool
        core.retro_get_memory_data.argtypes = [C.c_uint]
        core.retro_get_memory_data.restype = C.c_void_p
        core.retro_get_memory_size.argtypes = [C.c_uint]
        core.retro_get_memory_size.restype = C.c_size_t
        initialized = loaded = False
        try:
            core.retro_init()
            initialized = True
            content = str((args.content or ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue').resolve()).encode()
            loaded = core.retro_load_game(C.byref(Game(content, None, 0, None)))
            assert loaded, 'Core could not load the modified game'
            if args.enter_guest:
                assert args.content and args.check_guest and args.ram256
                payload = args.content.read_bytes()[0x800:]
                enter = core.retro_tm3o_test_enter_guest
                enter.argtypes = [C.c_void_p, C.c_size_t]
                enter.restype = C.c_bool
                assert enter(C.create_string_buffer(payload), len(payload))
            expected_code = (args.content or ROOT / 'diagnostics/sqrt_merge_v4/SCUS_942.49.sqrt_merge_v4').read_bytes()[0x800:0x840]
            code_loaded = False
            boot_frames = 0
            for boot_frames in range(1, 2401):
                core.retro_run()
                if boot_frames >= 120 and boot_frames % 30 == 0:
                    ram = core.retro_get_memory_data(2)
                    if ram and C.string_at(ram + 0x10000, 64) == expected_code:
                        code_loaded = True
                        break
            size = core.retro_serialize_size()
            assert 0 < size <= 512 * 1024 * 1024, size
            ram_bytes = core.retro_get_memory_size(2)
            if args.ram256:
                assert ram_bytes == 256 * 1024 * 1024, ram_bytes
            state = C.create_string_buffer(size)
            started = time.perf_counter()
            assert core.retro_serialize(state, size)
            save_ms = (time.perf_counter() - started) * 1000
            def ram_hash():
                length = core.retro_get_memory_size(2)
                assert 0 < length <= 256 * 1024 * 1024
                return hashlib.sha256(C.string_at(core.retro_get_memory_data(2), length)).hexdigest()
            before = ram_hash()
            mailbox = C.string_at(core.retro_get_memory_data(2) + 0x47900, 4).hex()
            for _ in range(30): core.retro_run()
            expected = ram_hash()
            if args.ram256:
                # Corrupt only the isolated instance AFTER saving. Restoration
                # must recover extended RAM, not just the legacy first 16 MiB.
                for offset in (0x01000000, 0x02000000, 0x0ffffffc):
                    C.memset(core.retro_get_memory_data(2) + offset, 0xa5, 4)
            started = time.perf_counter()
            assert core.retro_unserialize(state, size)
            load_ms = (time.perf_counter() - started) * 1000
            assert ram_hash() == before, 'Restore did not recover RAM'
            for _ in range(30): core.retro_run()
            actual = ram_hash()
            report = dict(content_loaded=True, tm3_mailbox_magic_hex=mailbox, ram_bytes=ram_bytes,
                test_entry_hook_used=args.enter_guest,
                game_executable_loaded=code_loaded, boot_frames=boot_frames,
                state_bytes=size, save_ms=save_ms,
                load_ms=load_ms, ram_restored=True, boot_replay_ram_equal=actual == expected,
                extension_restore_checked=args.ram256,
                replay_changed_ram=before != expected,
                linked_gameplay_tested=False, external_bridge_state_captured=False,
                video_audio_determinism_tested=False, production_runtime_modified=False)
            if args.content:
                markers = C.string_at(core.retro_get_memory_data(2) + 0x20000, 40)
                report['guest_markers_hex'] = markers.hex()
                if args.check_guest:
                    expected_markers = struct.pack('<10I',
                        *[0x4e455400 + i for i in range(4) for _ in range(2)], 0x1234, 0x50415353)
                    report['guest_cpu_access_and_execute_passed'] = markers == expected_markers
            target = args.report
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
            assert actual == expected, 'Boot replay RAM diverged'
            if args.check_guest:
                assert report['guest_cpu_access_and_execute_passed'], 'Guest CPU memory/execute test failed'
        finally:
            if loaded: core.retro_unload_game()
            if initialized: core.retro_deinit()


if __name__ == '__main__': main()
