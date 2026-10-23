"""SYSTEM256 libretro frontend primitives for the one-core-per-PC runtime.

The production online runtime creates one Core and exchanges ABI-6 cable
requests through its P2P endpoint. The legacy LocalCable helper remains for
local compatibility tests; it does not create another production console.
"""
import ctypes as C
import hashlib
from pathlib import Path
import shutil
import struct
import threading
import time


class Game(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]


class Variable(C.Structure):
    _fields_ = [('key', C.c_char_p), ('value', C.c_char_p)]


class LocalCable:
    """Legacy helper to pair two local cores in compatibility tests.

    No socket or wall-clock value enters the emulated state. The production
    online path uses PeerCable from network/system256_peer_cable.py instead.
    """
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = [None, None]
        self.ordinals = [{}, {}]
        self.exchanges = self.gameplay = self.time_mismatches = self.rng_mismatches = 0
        self.error = None
        self.stopped = False
        self.last_tail = None
        self.observer = None

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def exchange(self, side, ram, size):
        with self.condition:
            try:
                self._exchange(side, ram, size)
            except Exception as exc:
                self.error = str(exc)
                self.stopped = True
                struct.pack_into('<H', (C.c_ubyte * 112).from_address(ram + 0x47900), 6, 4)
                self.condition.notify_all()

    def _exchange(self, side, ram, size):
        header = (C.c_ubyte * 112).from_address(ram + 0x47900)
        magic, version, status, command, flags, seq, send_n, recv_n, _, call = struct.unpack_from('<I4H5I', header)
        assert magic == 0x4f334d54 and version == 6 and status == 1
        assert size == 256 * 1024 * 1024 and max(send_n, recv_n) <= 65536
        if self.stopped:
            struct.pack_into('<H', header, 6, 4)
            return
        if command == 1:
            struct.pack_into('<H', header, 10, 0x700 | (2 if side == 0 else 1))
            struct.pack_into('<I', header, 24, 0)
            struct.pack_into('<H', header, 6, 3)
            return
        assert command in (2, 3), command
        if command == 2:
            send_address, recv_address = struct.unpack_from('<II', header, 32)
            sends, receives = [(send_address, send_n)], [(recv_address, recv_n)]
        else:
            sn, rn = struct.unpack_from('<II', header, 40)
            assert sn <= 4 and rn <= 4
            sends = [struct.unpack_from('<II', header, 48 + 8*i) for i in range(sn)]
            receives = [struct.unpack_from('<II', header, 80 + 8*i) for i in range(rn)]
        def ranges(items):
            result = []
            for address, length in items:
                assert address >> 28 in (0, 8, 10) or length == 0
                offset = address & 0x0fffffff
                assert length <= 65536 and offset + length <= size
                result.append((ram + offset, length))
            return result
        sends, receives = ranges(sends), ranges(receives)
        assert sum(n for _, n in sends) == send_n
        assert sum(n for _, n in receives) == recv_n
        payload = b''.join(C.string_at(p, n) for p, n in sends)
        ordinal = self.ordinals[side].get(call, 0) + 1
        self.ordinals[side][call] = ordinal
        request = dict(header=header, payload=payload, receives=receives,
                       recv_n=recv_n, key=(command, call, ordinal), done=False)
        assert self.pending[side] is None
        self.pending[side] = request
        other = self.pending[1-side]
        if other:
            assert request['key'] == other['key'], (request['key'], other['key'])
            for dest, source in ((request, other), (other, request)):
                assert len(source['payload']) == dest['recv_n'], (len(source['payload']), dest['recv_n'], hex(call))
                position = 0
                for pointer, length in dest['receives']:
                    if length: C.memmove(pointer, source['payload'][position:position+length], length)
                    position += length
                struct.pack_into('<I', dest['header'], 24, len(source['payload']))
                struct.pack_into('<H', dest['header'], 6, 3)
                dest['done'] = True
            self.pending[:] = [None, None]
            self.exchanges += 1
            if command == 3 and call == 0x8003aa98:
                self.gameplay += 1
                a = struct.unpack_from('<II', payload, len(payload)-8)
                b = struct.unpack_from('<II', other['payload'], len(other['payload'])-8)
                self.last_tail = (a, b)
                self.time_mismatches += a[0] != b[0]
                self.rng_mismatches += a[1] != b[1]
                if self.observer: self.observer(self)
            self.condition.notify_all()
        deadline = time.monotonic() + 10
        while not request['done'] and not self.stopped:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError(f'Local console {side}: unmatched {request["key"]}')
            self.condition.wait(min(remaining, .2))
        if not request['done']: struct.pack_into('<H', header, 6, 4)


class VulkanFrontend:
    """Vulkan libretro frontend bridge with direct Win32 swapchain presentation."""
    def __init__(self, library):
        self.library = C.CDLL(str(Path(library).resolve()))
        self.library.tm3vk_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_char_p, C.c_size_t]
        self.library.tm3vk_probe.restype = C.c_int
        self.library.tm3vk_create_core.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        self.library.tm3vk_create_core.restype = C.c_void_p
        self.library.tm3vk_attach_core.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p,
                                                   C.c_int, C.c_char_p, C.c_size_t]
        self.library.tm3vk_attach_core.restype = C.c_int
        self.library.tm3vk_get_interface.argtypes = [C.c_void_p]
        self.library.tm3vk_get_interface.restype = C.c_void_p
        self.library.tm3vk_begin_frame.argtypes = [C.c_void_p]
        self.library.tm3vk_readback.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32,
                                                C.POINTER(C.c_void_p), C.POINTER(C.c_size_t),
                                                C.POINTER(C.c_uint), C.c_char_p, C.c_size_t]
        self.library.tm3vk_readback.restype = C.c_int
        self.library.tm3vk_end_frame.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        self.library.tm3vk_end_frame.restype = C.c_int
        self.library.tm3vk_present.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32,
                                               C.c_int, C.c_int, C.c_char_p, C.c_size_t]
        self.library.tm3vk_present.restype = C.c_int
        self.library.tm3vk_adapter_name.argtypes = [C.c_void_p]
        self.library.tm3vk_adapter_name.restype = C.c_char_p
        self.library.tm3vk_shutdown_core.argtypes = [C.c_void_p]

    @staticmethod
    def _error(buffer):
        return buffer.value.decode('utf-8', errors='replace') or 'Error Vulkan sin detalle.'

    def probe(self):
        adapter = C.create_string_buffer(256)
        error = C.create_string_buffer(512)
        ok = self.library.tm3vk_probe(adapter, len(adapter), error, len(error))
        return bool(ok), adapter.value.decode('utf-8', errors='replace'), self._error(error) if not ok else None

    def create_core(self, window_handle=None):
        error = C.create_string_buffer(512)
        hwnd = C.c_void_p(int(window_handle)) if window_handle else C.c_void_p()
        handle = self.library.tm3vk_create_core(hwnd, error, len(error))
        if not handle:
            raise RuntimeError(self._error(error))
        adapter = self.library.tm3vk_adapter_name(handle)
        return handle, adapter.decode('utf-8', errors='replace') if adapter else 'GPU Vulkan'

    def attach(self, handle, negotiation, hw_callback, visible):
        error = C.create_string_buffer(512)
        ok = self.library.tm3vk_attach_core(handle, C.c_void_p(negotiation),
                                            C.c_void_p(hw_callback), int(visible),
                                            error, len(error))
        if not ok:
            raise RuntimeError(self._error(error))

    def interface(self, handle):
        pointer = self.library.tm3vk_get_interface(handle)
        if not pointer:
            raise RuntimeError('No se pudo obtener la interfaz Vulkan de Beetle.')
        return pointer

    def begin_frame(self, handle):
        self.library.tm3vk_begin_frame(handle)

    def readback(self, handle, width, height):
        pixels, pitch, pixel_format = C.c_void_p(), C.c_size_t(), C.c_uint()
        error = C.create_string_buffer(512)
        ok = self.library.tm3vk_readback(handle, width, height, C.byref(pixels),
                                         C.byref(pitch), C.byref(pixel_format),
                                         error, len(error))
        if not ok:
            raise RuntimeError(self._error(error))
        return C.string_at(pixels, pitch.value * height), pitch.value, pixel_format.value

    def end_frame(self, handle):
        error = C.create_string_buffer(512)
        if not self.library.tm3vk_end_frame(handle, error, len(error)):
            raise RuntimeError(self._error(error))

    def present(self, handle, width, height, smooth=False, preserve_aspect=True):
        error = C.create_string_buffer(512)
        if not self.library.tm3vk_present(handle, width, height, int(smooth),
                                          int(preserve_aspect), error, len(error)):
            raise RuntimeError(self._error(error))

    def shutdown_core(self, handle):
        self.library.tm3vk_shutdown_core(handle)


class Core:
    def __init__(self, dll, content, folder, side, cable, inputs, audio_sink=None,
                 core_options=None, vulkan_frontend=None, hardware_core=False,
                 hardware_vulkan=False, visible=False, window_handle=None,
                 vulkan_smooth=False, vulkan_preserve_aspect=True):
        self.side, self.cable, self.inputs = side, cable, inputs
        # Copy PCM while the core owns its buffer; never retain its pointer.
        self.audio_sink = audio_sink
        self.audio_error = None
        self.core_options = dict(core_options or {})
        self.vulkan_frontend = vulkan_frontend
        self.vulkan_handle = None
        self.vulkan_ready = False
        self.video_visible = bool(visible)
        self.vulkan_present = bool(visible and window_handle)
        self.vulkan_smooth = bool(vulkan_smooth)
        self.vulkan_preserve_aspect = bool(vulkan_preserve_aspect)
        self.video_renderer = 'software'
        self.video_adapter = None
        self.render_error = None
        self.hardware_core = bool(hardware_core)
        self.hardware_vulkan = bool(hardware_vulkan)
        self.hw_option_prefix = b'beetle_psx_hw_' if hardware_core else b'beetle_psx_'
        self.hw_callback_ptr = None
        self.vulkan_negotiation_ptr = None
        self._initialized = False
        self._game_loaded = False
        self._closed = False
        self.frame, self.video, self.video_frames, self.video_frames_presented, self.pixel_format = 0, None, 0, 0, 1
        self.callbacks, self.vars = [], {}
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / f'console_{side}.dll'
        shutil.copy2(dll, target)
        self.dll = C.CDLL(str(target.resolve()))
        self.directory = str(self.folder.resolve()).encode()
        self.pads = (0, 0)
        self.input_calls = self.pressed_calls = 0
        self.transitions = []
        self.last_menu = None
        def callback(name, signature, fn):
            wrapped = signature(fn); self.callbacks.append(wrapped)
            setter = getattr(self.dll, name); setter.argtypes = [type(wrapped)]; setter(wrapped)
        callback('retro_set_environment', C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p), self.environment)
        callback('retro_set_video_refresh', C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t), self.render)
        callback('retro_set_audio_sample', C.CFUNCTYPE(None, C.c_int16, C.c_int16), self.audio_sample)
        callback('retro_set_audio_sample_batch', C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t), self.audio_batch)
        callback('retro_set_input_poll', C.CFUNCTYPE(None), lambda:None)
        callback('retro_set_input_state', C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint), self.input)
        self.exchange_callback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_size_t)(
            lambda context, ram, size: cable.exchange(side, ram, size))
        self.dll.retro_tm3o_set_local_exchange.argtypes = [type(self.exchange_callback), C.c_void_p]
        self.dll.retro_tm3o_set_local_exchange(self.exchange_callback, None)
        self.dll.retro_load_game.argtypes = [C.POINTER(Game)]
        self.dll.retro_load_game.restype = C.c_bool
        self.dll.retro_get_memory_data.argtypes = [C.c_uint]
        self.dll.retro_get_memory_data.restype = C.c_void_p
        self.dll.retro_get_memory_size.restype = C.c_size_t
        if hardware_core:
            if hardware_vulkan and vulkan_frontend is not None:
                try:
                    self.vulkan_handle, self.video_adapter = vulkan_frontend.create_core(
                        window_handle if self.vulkan_present else None)
                except Exception:
                    self.close()
                    raise
            self.core_options[self.hw_option_prefix + b'renderer'] = (
                b'hardware_vk' if self.vulkan_handle else b'software')
        self.dll.retro_init()
        self._initialized = True
        if not self.dll.retro_load_game(C.byref(Game(str(Path(content).resolve()).encode(), None, 0, None))):
            self.close()
            raise RuntimeError('El core no pudo cargar el juego SYSTEM256.')
        self._game_loaded = True
        if self.vulkan_handle:
            if not self.hw_callback_ptr or not self.vulkan_negotiation_ptr:
                self.close()
                raise RuntimeError('El core no completo la negociacion del contexto Vulkan.')
            try:
                vulkan_frontend.attach(self.vulkan_handle, self.vulkan_negotiation_ptr,
                                       self.hw_callback_ptr, self.video_visible)
            except Exception:
                self.close()
                raise
            self.vulkan_ready = True
            self.video_renderer = 'vulkan'
        self.dll.retro_set_controller_port_device(0, 1)
        self.dll.retro_set_controller_port_device(1, 1)
        self.ram = self.dll.retro_get_memory_data(2)
        if self.dll.retro_get_memory_size(2) != 256 * 1024 * 1024:
            self.close()
            raise RuntimeError('La RAM del core no coincide con SYSTEM256.')
        # The stable BIN already calls this deterministic RNG trampoline.
        rng = [0x8F820708,0x3C0880F0,0x8D090010,0,0x312A0FFF,0x000A5100,
               0x250B0020,0x016A5821,0xAD7F0000,0xAD620004,0x25290001,
               0xAD090010,0x3C0341C6,0x0800E83E,0]
        C.memmove(self.ram + 0xf10100, struct.pack('<15I', *rng), 60)

    def audio_sample(self, left, right):
        if self.audio_sink is not None and self.audio_error is None:
            try:
                self.audio_sink(struct.pack('<hh', left, right))
            except Exception as exc:
                self.audio_error = repr(exc)

    def audio_batch(self, data, frames):
        if self.audio_sink is not None and self.audio_error is None:
            try:
                if frames > 65536 or (frames and not data):
                    raise ValueError('Invalid stereo PCM batch')
                if frames:
                    self.audio_sink(C.string_at(data, frames * 4))
            except Exception as exc:
                self.audio_error = repr(exc)
        return frames

    def environment(self, command, data):
        if command == 14:  # RETRO_ENVIRONMENT_SET_HW_RENDER
            callback = C.cast(data, C.c_void_p).value
            if not self.hardware_core or not self.hardware_vulkan or not self.vulkan_handle or not callback:
                return False
            self.hw_callback_ptr = callback
            return True
        if command == (43 | 0x10000):  # Vulkan context-negotiation interface
            if not self.hardware_vulkan or not self.vulkan_handle or not data:
                return False
            self.vulkan_negotiation_ptr = C.cast(data, C.c_void_p).value
            return True
        if command == (41 | 0x10000):  # GET_HW_RENDER_INTERFACE
            if not self.vulkan_handle or not data:
                return False
            C.cast(data, C.POINTER(C.c_void_p))[0] = self.vulkan_frontend.interface(self.vulkan_handle)
            return True
        if command in (9, 30, 31):
            C.cast(data, C.POINTER(C.c_char_p))[0] = self.directory; return True
        if command == 3:
            C.cast(data, C.POINTER(C.c_bool))[0] = True; return True
        if command == 10:
            self.pixel_format = C.cast(data, C.POINTER(C.c_int))[0]; return True
        if command == 16:
            variables = C.cast(data, C.POINTER(Variable)); i = 0
            while variables[i].key:
                key, value = variables[i].key, variables[i].value
                self.vars[key] = value.split(b';',1)[-1].strip().split(b'|',1)[0]
                i += 1
            return True
        if command == 15:
            variable = C.cast(data, C.POINTER(Variable))[0]
            # Match the installed TM3 CPU175 budget; no change to TIME/RNG.
            variable.value = (b'175%' if variable.key in
                              (b'beetle_psx_cpu_freq_scale', b'beetle_psx_hw_cpu_freq_scale')
                              else self.core_options.get(variable.key, self.vars.get(variable.key)))
            return variable.value is not None
        if command == 17:
            C.cast(data, C.POINTER(C.c_bool))[0] = False; return True
        if command == 44:
            C.cast(data, C.POINTER(C.c_uint64))[0] |= 8; return True
        return command in (8, 11, 13, 18, 32, 35, 36, 37)

    def input(self, port, device, index, button):
        self.input_calls += 1
        if port > 1 or device != 1: return 0
        value = self.pads[port]
        if value: self.pressed_calls += 1
        return C.c_int16(value).value if button == 256 else int(button < 16 and bool(value & (1 << button)))

    def render(self, data, width, height, pitch):
        if self.vulkan_ready:
            try:
                hw_frame = data == C.c_void_p(-1).value
                if hw_frame and width and height:
                    self.video_frames += 1
                    if self.vulkan_present:
                        self.vulkan_frontend.present(self.vulkan_handle, width, height,
                                smooth=self.vulkan_smooth,
                                preserve_aspect=self.vulkan_preserve_aspect)
                        self.video_frames_presented += 1
                    else:
                        self.vulkan_frontend.end_frame(self.vulkan_handle)
                elif not data:
                    self.vulkan_frontend.end_frame(self.vulkan_handle)
            except Exception as exc:
                self.render_error = 'Error de renderizado Vulkan: ' + repr(exc)
            return
        if data and width and height and pitch <= 16384 and height <= 2048:
            self.video_frames += 1
            # Capture occasionally, not every render; gameplay benchmarks can
            # disable this copy independently of actual emulation/rendering.
            capture_every = getattr(self, 'capture_every', 10)
            if capture_every and self.frame % capture_every == 0:
                self.video = (C.string_at(data, pitch * height), width, height, pitch, self.pixel_format)

    def word(self, offset): return C.c_uint32.from_address(self.ram + offset).value

    def step(self):
        self.pads = self.inputs(self.side, self.frame)
        if self.word(0x47900) == 0x4f334d54:
            C.c_uint16.from_address(self.ram + 0x4790a).value = 0x700 | (2 if self.side == 0 else 1)
        if self.vulkan_ready:
            self.vulkan_frontend.begin_frame(self.vulkan_handle)
        self.dll.retro_run(); self.frame += 1
        if self.render_error:
            raise RuntimeError(self.render_error)
        menu = self.word(0x89a0c)
        if menu != self.last_menu:
            self.transitions.append(dict(frame=self.frame,menu=hex(menu),
                flags=hex(self.word(0x47908)), new_target=hex(self.word(0x7fef8))))
            self.last_menu = menu

    def screenshot(self, path):
        if not self.video: return
        data, width, height, pitch, fmt = self.video
        pixels = bytearray()
        for y in range(height):
            row = data[y*pitch:(y+1)*pitch]
            if fmt == 1: pixels.extend(row[:width*4])
            else:
                for x in range(width):
                    v = struct.unpack_from('<H', row, x*2)[0]
                    b = (v & 31)*255//31
                    g = ((v >> 5) & (63 if fmt == 2 else 31))*255//(63 if fmt == 2 else 31)
                    r = ((v >> (11 if fmt == 2 else 10)) & 31)*255//31
                    pixels.extend((b,g,r,0))
        header = struct.pack('<2sIHHI', b'BM', 54+len(pixels), 0,0,54)
        header += struct.pack('<IiiHHIIiiII', 40,width,-height,1,32,0,len(pixels),0,0,0,0)
        Path(path).write_bytes(header + pixels)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._game_loaded:
            self.dll.retro_unload_game()
            self._game_loaded = False
        if self._initialized:
            self.dll.retro_deinit()
            self._initialized = False
        if self.vulkan_handle:
            self.vulkan_frontend.shutdown_core(self.vulkan_handle)
            self.vulkan_handle = None
        import _ctypes
        _ctypes.FreeLibrary(self.dll._handle)
