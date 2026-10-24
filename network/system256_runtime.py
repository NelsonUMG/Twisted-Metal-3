"""One local console per PC; ABI-6 cable traffic crosses the authenticated P2P link."""
import argparse
import configparser
import ctypes as C
import hashlib
import json
from multiprocessing.connection import Client
import os
from pathlib import Path
import queue
import struct
import tempfile
import threading
import time
import traceback
from collections import deque

from twin_core import Core, VulkanFrontend
from system256_peer_cable import PeerCable
from system256_menu_sync import MenuReturnSync
from ui_work import SoftwarePresentation


class Link:
    def __init__(self, port, key):
        self.connection = Client(('127.0.0.1', port), authkey=bytes.fromhex(key))
        self.messages = queue.Queue(32)
        self.cable = None
        self.lock = threading.Lock()
        self.error = None
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.receive, daemon=True)
        self.thread.start()

    def send(self, packet):
        with self.lock:
            self.connection.send_bytes(packet)

    def send_cable(self, packet):
        self.send(b'C' + packet)

    def receive(self):
        try:
            while not self.closed.is_set():
                packet = self.connection.recv_bytes(36 + 64 * 1024 + 1)
                if packet[:1] == b'M':
                    if len(packet) > 2049:
                        raise ValueError('Oversized engine control packet')
                    self.messages.put_nowait(json.loads(packet[1:]))
                elif packet[:1] == b'C' and self.cable is not None:
                    self.cable.receive(packet[1:])
                else:
                    raise ValueError('Invalid IPC envelope')
        except (OSError, EOFError, ValueError, queue.Full) as exc:
            if not self.closed.is_set():
                self.error = repr(exc)
                if self.cable:
                    self.cable.stop(self.error)

    def close(self):
        self.closed.set()
        if self.cable:
            self.cable.stop()
        self.connection.close()


class Pad(C.Structure):
    _fields_ = [('buttons', C.c_ushort), ('left', C.c_ubyte), ('right', C.c_ubyte),
                ('lx', C.c_short), ('ly', C.c_short), ('rx', C.c_short), ('ry', C.c_short)]


class State(C.Structure):
    _fields_ = [('packet', C.c_uint), ('pad', Pad)]


def controller_mask(index):
    state = State()
    if not 0 <= index <= 3 or C.windll.xinput1_4.XInputGetState(index, C.byref(state)):
        return None
    p = state.pad
    # Matches the installed native frontend's logical pad binding numbers.
    masks = [0, 0x1000, 0x2000, 0x4000, 0x8000, 0x20, 0x10,
             1, 2, 4, 8, 0x100, 0x200, 0, 0, 0x40, 0x80]
    result = sum(1 << i for i, mask in enumerate(masks) if mask and p.buttons & mask)
    if p.left > 30: result |= 1 << 13
    if p.right > 30: result |= 1 << 14
    for value, positive, negative, threshold in ((p.ly,17,18,7849), (p.lx,20,19,7849),
                                                 (p.ry,21,22,8689), (p.rx,24,23,8689)):
        if value > threshold: result |= 1 << positive
        if value < -threshold: result |= 1 << negative
    return result


def run(args):
    import pygame
    folder = Path(args.assets)
    dll_search_handle = os.add_dll_directory(str(folder.resolve())) if os.name == 'nt' else None
    qa_recording = json.loads(Path(args.qa_fixture).read_text())['input_recording'] if args.qa_fixture else None
    configuration = configparser.ConfigParser()
    configuration.read(args.settings, encoding='utf-8-sig')
    settings = configuration['Console'] if configuration.has_section('Console') else {}
    def option(name, default=0):
        try: return int(settings.get(name, default))
        except (ValueError, TypeError): return default
    state_path = Path(args.state)
    history = deque(maxlen=240)
    log_directory = Path(args.log_directory) if args.log_directory else state_path.parent
    history_path = log_directory / 'LOG_TM3_ONLINE.txt'
    status_lock = threading.RLock()
    def status(state, **extra):
        # Role events arrive on the receiver/core threads while the UI also
        # publishes its heartbeat. Serialize the shared .tmp -> state replace.
        with status_lock:
            write_status(state, **extra)
    def write_status(state, **extra):
        value = dict(state=state, engine='SYSTEM256-CABLE-P2P1', real_transport=True,
                     one_console_per_pc=True, pid=os.getpid())
        value.update(extra)
        now = time.time()
        history.append(dict(timestamp=now, **value))
        while history and history[0]['timestamp'] < now - 120:
            history.popleft()
        try:
            history_path.write_text('TM3 Online — últimos 120 segundos\n' +
                                   json.dumps(list(history), indent=2, ensure_ascii=False), encoding='utf-8-sig')
        except OSError:
            # Diagnostic logging must never stop a running console.
            pass
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    prefix=f'.{state_path.stem}.', suffix='.tmp',
                    dir=state_path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(value))
            for attempt in range(6):
                try:
                    os.replace(temporary, state_path)
                    temporary = None
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.02 * (attempt + 1))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    status('starting')
    link = None; cores = []; threads = []; cable = None; temporary_owner = None
    vulkan_frontend = None; hardware_core = False; use_vulkan = False; video_adapter = None
    native_ui = None; native_handle = None; native_tick = None
    capture_requested = threading.Event()
    stop = threading.Event(); errors = []; pcm = queue.Queue(64)
    audio_stats = {'pcm_generated_bytes': 0, 'pcm_queue_dropped_bytes': 0,
                   'pcm_stale_dropped_bytes': 0, 'audio_output_bytes': 0,
                   'audio_output_chunks': 0, 'audio_underruns': 0,
                   'first_pcm_generated_at': None, 'audio_started': False,
                   'audio_start_delay_ms': None, 'audio_error': None}
    audio_stats_lock = threading.Lock()
    audio_stop = threading.Event(); audio_thread = None
    pygame.display.init()
    audio_error = None
    try:
        from pygame._sdl2.audio import get_audio_device_names
        names = get_audio_device_names(False)
    except Exception: names = []
    device = settings.get('AudioDeviceName')
    if device and device not in names:
        device = next((name for name in names if name.startswith(device)), None)
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512,
                          devicename=device if device in names else None)
        audio = pygame.mixer.Channel(0)
        audio.set_volume(0 if option('Muted') else max(0, min(100, option('Volume', 100))) / 100)
    except pygame.error as exc:
        raise RuntimeError('No se pudo abrir el audio: ' + str(exc))
    surface = pygame.display.set_mode((960, 720), pygame.RESIZABLE)
    window_handle = pygame.display.get_wm_info().get('window')
    if hasattr(window_handle, 'value'):
        window_handle = window_handle.value
    if not isinstance(window_handle, int) or window_handle <= 0:
        window_handle = None
    pygame.display.set_caption('TM3 Online — SYSTEM256 — conectando')
    focused = threading.Event(); focused.set()
    def sample(frame):
        if not focused.is_set(): return 0
        result = 0; selected = []
        for port in (0, 1):
            if port and not option('Player2Enabled'): continue
            prefix = 'Player2' if port else ''
            index = option('Player2ControllerIndex', -1) if port else option('ControllerIndex')
            if index < 0: index = next((i for i in range(4) if i not in selected and controller_mask(i) is not None), -1)
            if index in selected: index = -1
            if index >= 0: selected.append(index)
            mask = (controller_mask(index) or 0) if option('Controller', 1) else 0
            for button in range(16):
                key = option(f'{prefix}Key{button}')
                binding = option(f'{prefix}Pad{button}')
                if ((key > 0 and C.windll.user32.GetAsyncKeyState(key) & 0x8000)
                        or (0 < binding <= 24 and mask & (1 << binding))):
                    result |= 1 << (button + 16 * port)
        return result
    def sink(data):
        with audio_stats_lock:
            audio_stats['pcm_generated_bytes'] += len(data)
            if audio_stats['first_pcm_generated_at'] is None and data:
                audio_stats['first_pcm_generated_at'] = time.monotonic()
        try: pcm.put_nowait(data)
        except queue.Full:
            with audio_stats_lock:
                audio_stats['pcm_queue_dropped_bytes'] += len(data)
            # Never stall deterministic gameplay on audio.
    def play_audio():
        pending = bytearray()
        started = False
        max_pending = round(44100 * 0.25) * 4
        try:
            while not audio_stop.is_set() or not pcm.empty():
                try:
                    pending.extend(pcm.get(timeout=0.004))
                except queue.Empty:
                    pass
                if len(pending) > max_pending:
                    discard = (len(pending) - max_pending) // 4 * 4
                    del pending[:discard]
                    with audio_stats_lock:
                        audio_stats['pcm_stale_dropped_bytes'] += discard
                if not pending or (started and audio.get_queue()):
                    continue
                size = min(len(pending), 8192) // 4 * 4
                if not size:
                    continue
                sound = pygame.mixer.Sound(buffer=bytes(pending[:size]))
                del pending[:size]
                if audio.get_busy():
                    audio.queue(sound)
                else:
                    audio.play(sound)
                    if started:
                        with audio_stats_lock:
                            audio_stats['audio_underruns'] += 1
                if not started:
                    started = True
                    with audio_stats_lock:
                        first_pcm_at = audio_stats['first_pcm_generated_at']
                        audio_stats['audio_started'] = True
                        if first_pcm_at is not None:
                            audio_stats['audio_start_delay_ms'] = round(
                                (time.monotonic() - first_pcm_at) * 1000, 2)
                with audio_stats_lock:
                    audio_stats['audio_output_bytes'] += size
                    audio_stats['audio_output_chunks'] += 1
        except BaseException as exc:
            with audio_stats_lock:
                audio_stats['audio_error'] = repr(exc)
            audio_stop.set()
    try:
        bios = settings.get('BIOS', '')
        if bios:
            bios_path = Path(bios)
            if not bios_path.is_absolute(): bios_path = Path(args.settings).parent / bios_path
            if not bios_path.is_file(): raise ValueError('No se encontró el BIOS configurado.')
            os.environ['TM3O_BIOS_PATH'] = str(bios_path.resolve())
        link = Link(args.port, args.key)
        audio_thread = threading.Thread(target=play_audio, name='TM3-local-audio', daemon=True)
        audio_thread.start()
        def digest(path):
            with path.open('rb') as source: return hashlib.file_digest(source, 'sha256').hexdigest()
        hardware_dll = folder/'beetle_psx_system256_vulkan.dll'
        software_dll = folder/'beetle_psx_system256.dll'
        has_hardware_core = hardware_dll.is_file()
        has_software_core = software_dll.is_file()
        if not (has_hardware_core or has_software_core):
            raise ValueError('Falta el core Beetle PSX de SYSTEM256.')
        helper_path = folder/'tm3_vulkan_frontend.dll'
        local_vulkan = False
        if has_hardware_core and helper_path.is_file():
            try:
                vulkan_frontend = VulkanFrontend(helper_path)
                local_vulkan, local_adapter, probe_error = vulkan_frontend.probe()
                if not local_vulkan:
                    vulkan_frontend = None
            except (OSError, AttributeError, RuntimeError):
                local_vulkan = False
                vulkan_frontend = None
        # Negotiate against the common software core first. The HW core hash is
        # checked only if both PCs can actually initialize Vulkan.
        common_core = software_dll if has_software_core else hardware_dll
        manifest = dict(protocol='SYSTEM256-CABLE-P2P1', core=digest(common_core),
                        core_vulkan=digest(hardware_dll) if has_hardware_core else None,
                        game=digest(folder/'TM3_SYSTEM256.bin'), epoch=str(args.epoch),
                        cpu=175, ram=268435456,
                        vulkan_available=bool(local_vulkan))
        link.send(b'M' + json.dumps(manifest).encode())
        deadline = time.monotonic() + 45
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT: return
            if link.error: raise RuntimeError(link.error)
            try:
                remote = link.messages.get(timeout=.05)
                if not isinstance(remote, dict):
                    raise ValueError('La otra PC no informó su motor.')
                ignored = ('vulkan_available', 'core_vulkan')
                if ({k:v for k,v in remote.items() if k not in ignored}
                        != {k:v for k,v in manifest.items() if k not in ignored}):
                    raise ValueError('La otra PC tiene un motor, juego o ajuste incompatible.')
                if type(remote.get('vulkan_available')) is not bool:
                    raise ValueError('La otra PC no informó compatibilidad de vídeo.')
                use_vulkan = bool(local_vulkan and remote['vulkan_available']
                                  and has_hardware_core
                                  and remote.get('core_vulkan') == manifest['core_vulkan'])
                break
            except queue.Empty:
                if time.monotonic() > deadline: raise TimeoutError('El otro lobby no confirmó SYSTEM256.')
        temporary_owner = tempfile.TemporaryDirectory(prefix='tm3_system256_', ignore_cleanup_errors=True)
        temporary = temporary_owner.name
        qa_delayed_phases = set()
        def send_cable_packet(packet):
            if qa_recording and args.side == 1 and len(packet) >= 4:
                phase = None
                delay_ms = 0
                if packet[:4] == b'T3R1':
                    phase = 'online_mode'
                    delay_ms = args.qa_delay_online_ms
                elif packet[:4] == b'T3C1' and len(packet) >= 36:
                    call = struct.unpack_from('!4sQBBHIIIII', packet)[7]
                    if call in (0x80047EA0, 0x80047EB8):
                        phase = 'vehicle_selection'
                        delay_ms = args.qa_delay_vehicle_ms
                if phase and delay_ms and phase not in qa_delayed_phases:
                    qa_delayed_phases.add(phase)
                    time.sleep(delay_ms / 1000)
            link.send_cable(packet)
        cable = PeerCable(args.side, args.epoch, send_cable_packet)
        link.cable = cable
        menu_sync = MenuReturnSync()
        if True:
            recording = qa_recording[args.side] if qa_recording else None
            qa_input_events = deque(maxlen=256)
            qa_last_input = [None]
            def local_inputs(_role, frame):
                packed = (recording[frame] if recording and frame < len(recording)
                          else 0 if recording else sample(frame))
                if cores:
                    packed = menu_sync.local_input(
                        packed, frame, cores[0].word(0x89a0c),
                        cable.role_agreed, cable.match_active)
                if qa_recording and packed != qa_last_input[0] and cores and not cable.gameplay:
                    qa_input_events.append(dict(frame=frame, monotonic=time.monotonic(),
                                                mask=packed, menu=hex(cores[0].word(0x89a0c))))
                qa_last_input[0] = packed
                return packed & 0xFFFF, (packed >> 16) & 0xFFFF
            resolution = args.qa_resolution or option('Resolution', 1)
            if resolution not in (1,2,4): resolution = 1
            def build_cores(enable_vulkan):
                built = []
                # If Vulkan is unavailable on either PC, use the original
                # optimized software core on both, not the HW core's SW path.
                core_path = (hardware_dll if enable_vulkan or not has_software_core
                             else software_dll)
                selected_hardware_core = core_path == hardware_dll
                option_prefix = (b'beetle_psx_hw_' if selected_hardware_core
                                 else b'beetle_psx_')
                selected_options = {
                    option_prefix + b'internal_resolution': b'1x(native)' if resolution == 1 else f'{resolution}x'.encode(),
                    option_prefix + b'pgxp_mode': b'memory only' if option('PGXP') else b'disabled',
                    option_prefix + b'widescreen_hack': b'enabled' if option('Widescreen') else b'disabled',
                    option_prefix + b'widescreen_hack_aspect_ratio': b'16:9'}
                if selected_hardware_core:
                    selected_options[option_prefix + b'renderer'] = (
                        b'hardware_vk' if enable_vulkan else b'software')
                try:
                    core = Core(core_path, folder/'TM3_SYSTEM256.cue',
                                Path(temporary)/str(args.side), args.side, cable, local_inputs,
                                audio_sink=sink,
                                core_options=selected_options,
                                vulkan_frontend=vulkan_frontend,
                                hardware_core=selected_hardware_core,
                                hardware_vulkan=enable_vulkan,
                                visible=window_handle is not None,
                                window_handle=window_handle,
                                vulkan_smooth=bool(option('Smooth')),
                                vulkan_preserve_aspect=True)
                    core.capture_every = 1
                    built.append(core)
                    if enable_vulkan and core.video_renderer != 'vulkan':
                        raise RuntimeError('Una consola no confirmó el renderizador Vulkan.')
                    return built
                except Exception:
                    for core in reversed(built):
                        core.close()
                    raise

            load_error = None
            try:
                cores = build_cores(use_vulkan)
            except Exception as exc:
                if not use_vulkan:
                    load_error = str(exc)
                else:
                    # A probe can succeed while device, surface, swapchain or
                    # core context creation fails. Prefer a synchronized
                    # software fallback to stranding the other peer.
                    use_vulkan = False
                    try:
                        cores = build_cores(False)
                    except Exception as fallback_exc:
                        load_error = f'Vulkan falló ({exc}); también falló software ({fallback_exc}).'

            core = cores[0] if cores else None
            actual_backend = core.video_renderer if core else None
            local_loaded = {'loaded': bool(cores), 'video_backend': actual_backend,
                            'error': load_error}
            link.send(b'M' + json.dumps(local_loaded).encode())
            if not cores:
                raise RuntimeError(load_error or 'No se pudieron iniciar las consolas.')
            def observe_role(event):
                event['frame'] = core.frame
                status('role_waiting' if event['event'] == 'local_yes' else 'connected',
                       role_event=event, role_events=list(cable.role_events),
                       role_waiting=cable.role_pending is not None)
            cable.role_observer = observe_role
            remote_loaded = link.messages.get(timeout=45)
            if not isinstance(remote_loaded, dict) or remote_loaded.get('loaded') is not True:
                raise ValueError((remote_loaded.get('error') if isinstance(remote_loaded, dict) else None)
                or 'La otra PC no cargó su consola.')

            if remote_loaded.get('video_backend') not in ('software', 'vulkan'):
                raise ValueError('La otra PC no informó un renderizador compatible.')
            # Both peers must choose the same renderer. If either side had to
            # fall back during device creation, rebuild the Vulkan side too.
            if actual_backend != 'vulkan' or remote_loaded['video_backend'] != 'vulkan':
                if actual_backend == 'vulkan':
                    for core in reversed(cores):
                        core.close()
                    cores.clear()
                    cores = build_cores(False)
                core = cores[0]
                actual_backend = core.video_renderer

            link.send(b'M' + json.dumps({'ready': True, 'video_backend': actual_backend}).encode())
            remote_ready = link.messages.get(timeout=45)
            if (not isinstance(remote_ready, dict) or remote_ready.get('ready') is not True
                    or remote_ready.get('video_backend') != actual_backend):
                raise ValueError('Las dos PC no acordaron el mismo renderizador de vídeo.')

            video_adapter = core.video_adapter
            ui_path = folder/'TM3System256UI.dll'
            if window_handle and ui_path.is_file():
                native_ui = C.CDLL(str(ui_path.resolve()))
                native_ui.tm3ui_attach.argtypes = [C.c_void_p, C.c_wchar_p, C.c_wchar_p, C.c_int]
                native_ui.tm3ui_attach.restype = C.c_void_p
                native_ui.tm3ui_poll.argtypes = [C.c_void_p]
                native_ui.tm3ui_pump.argtypes = [C.c_void_p]
                native_ui.tm3ui_pump.restype = None
                native_waiting = getattr(native_ui, 'tm3ui_set_waiting', None)
                if native_waiting:
                    native_waiting.argtypes = [C.c_void_p, C.c_int]
                    native_waiting.restype = None
                native_ui.tm3ui_detach.argtypes = [C.c_void_p]
                native_handle = native_ui.tm3ui_attach(window_handle, str(Path(args.settings).resolve().parent),
                    str((folder/'TM3_SYSTEM256.cue').resolve()), actual_backend == 'vulkan')
                if not native_handle: raise RuntimeError('No se pudo abrir la interfaz de SYSTEM256.')

            start = time.perf_counter()
            qa_times = []; qa_hashes = []
            qa_target = args.qa_gameplay_ticks
            def observe(c):
                if not qa_recording: return
                if c.gameplay in (30, qa_target): qa_times.append((time.perf_counter(), core.word(0x895a8)))
                if c.gameplay == qa_target:
                    qa_hashes.append(hashlib.sha256(C.string_at(core.ram,16*1024*1024)).hexdigest())
                    stop.set()
            cable.observer = observe
            def execute(core):
                main_menu = MenuReturnSync.MAIN_MENU
                was_main_menu = False
                try:
                    while not stop.is_set() and not cable.stopped:
                        core.step()
                        if capture_requested.is_set():
                            capture_requested.clear()
                            captures = Path(args.settings).resolve().parent/'captures'
                            captures.mkdir(exist_ok=True)
                            core.screenshot(str(captures/f'TM3_{time.time_ns()}.bmp'))
                        if args.qa_screenshot and core.transitions and core.transitions[-1]['frame'] == core.frame:
                            core.screenshot(str(Path(args.qa_screenshot).with_name(f'menu{args.side}_{core.frame}.bmp')))
                        is_main_menu = core.word(0x89a0c) == main_menu
                        if is_main_menu and not was_main_menu and cable.role_agreed:
                            cable.reset_role_cycle()
                        was_main_menu = is_main_menu
                        wait = start + core.frame / 59.94 - time.perf_counter()
                        if wait > 0: stop.wait(wait)
                except BaseException as exc:
                    if not stop.is_set(): errors.append(repr(exc))
                    stop.set(); cable.stop()
            threads = [threading.Thread(target=execute, args=(core,), daemon=True) for core in cores]
            for thread in threads: thread.start()
            status('connected', video_backend=actual_backend,
                   video_adapter=video_adapter, local_core_count=len(cores))
            renderer_label = ('Vulkan' + (f' — {video_adapter}' if video_adapter else '')
                              if actual_backend == 'vulkan' else 'Software')
            base_caption = f'TM3 Online — SYSTEM256 — {renderer_label} — Esc: volver al lobby'
            waiting_label = ('Esperando a la otra consola' if option('Language') == 1
                             else 'Waiting for other console')
            returning_label = ('Volviendo al menú principal' if option('Language') == 1
                               else 'Returning to main menu')
            displayed_caption = base_caption
            pygame.display.set_caption(base_caption)
            clock = pygame.time.Clock(); last_status = time.monotonic()
            video_frames_presented = 0
            last_presented_frame = -1
            fullscreen = False
            settings_stamp = None
            settings_path = Path(args.settings)
            next_settings_check = 0
            presentation = SoftwarePresentation()
            modal_ticks = 0
            modal_presented = 0
            displayed_wait_phase = None
            displayed_waiting_overlay = False
            wait_screenshots = {}
            pygame.font.init()
            waiting_font = pygame.font.SysFont('Arial', 18, bold=True)
            def present_video(exposed=False):
                nonlocal video_frames_presented, last_presented_frame
                video = core.video
                if presentation.needed(video, surface.get_size(), option('Smooth'), exposed):
                    data, width, height, pitch, fmt = video
                    if fmt not in (1, 3, 4): raise RuntimeError('Formato de vídeo no compatible con este presentador.')
                    packed = data if pitch == width*4 else b''.join(data[y*pitch:y*pitch+width*4] for y in range(height))
                    image = pygame.image.frombuffer(packed, (width, height), 'BGRA' if fmt in (1, 4) else 'RGBA')
                    image.set_alpha(None)
                    dw, dh = surface.get_size()
                    scale = min(dw / 4, dh / 3); target = (int(scale*4), int(scale*3))
                    image = (pygame.transform.smoothscale if option('Smooth') else pygame.transform.scale)(image, target)
                    surface.fill((0,0,0)); surface.blit(image, ((dw-target[0])//2, (dh-target[1])//2))
                    if displayed_waiting_overlay:
                        message = waiting_font.render('WAITING FOR OTHER CONSOLE', True, (255, 255, 255))
                        padding_x, padding_y = 12, 6
                        panel = pygame.Surface((message.get_width()+padding_x*2,
                                                message.get_height()+padding_y*2), pygame.SRCALPHA)
                        panel.fill((5, 8, 14, 220))
                        x = (dw-panel.get_width())//2
                        y = int(dh*.46-panel.get_height()/2)
                        surface.blit(panel, (x, y))
                        surface.blit(message, (x+padding_x, y+padding_y))
                    pygame.display.flip()
                    current_frame = core.frame
                    if current_frame > last_presented_frame:
                        video_frames_presented += 1
                        last_presented_frame = current_frame
            def modal_frame(_context):
                nonlocal modal_ticks, modal_presented
                if stop.is_set(): return
                try:
                    modal_ticks += 1
                    before = video_frames_presented
                    present_video()
                    modal_presented += video_frames_presented - before
                except Exception as exc:
                    errors.append(repr(exc)); stop.set()
            if native_handle and actual_backend == 'software':
                native_tick = C.CFUNCTYPE(None, C.c_void_p)(modal_frame)
                native_ui.tm3ui_set_tick.argtypes = [C.c_void_p, type(native_tick), C.c_void_p]
                native_ui.tm3ui_set_tick.restype = None
                native_ui.tm3ui_set_tick(native_handle, native_tick, None)
            while not stop.is_set():
                if native_handle:
                    native_ui.tm3ui_pump(native_handle)
                if native_handle and native_ui.tm3ui_poll(native_handle) == 1:
                    capture_requested.set()
                if menu_sync.consume_broadcast():
                    link.send(b'M' + json.dumps({'action': MenuReturnSync.ACTION}).encode())
                while True:
                    try:
                        control = link.messages.get_nowait()
                    except queue.Empty:
                        break
                    if isinstance(control, dict) and control.get('action') == MenuReturnSync.ACTION:
                        menu_sync.request_remote_return()
                cable_wait = cable.waiting_snapshot()
                wait_phase = (cable_wait['phase'] if cable_wait and cable_wait['seconds'] >= .5
                              else None)
                if wait_phase != displayed_wait_phase:
                    displayed_wait_phase = wait_phase
                    displayed_waiting_overlay = wait_phase == 'vehicle_selection'
                    if native_handle and native_waiting:
                        native_waiting(native_handle, int(displayed_waiting_overlay))
                if (qa_recording and args.qa_screenshot and wait_phase
                        and wait_phase not in wait_screenshots):
                    # Force composition while the emulated menu is waiting;
                    # the game framebuffer is frozen between callback pumps.
                    present_video(exposed=True)
                    wait_capture = Path(args.qa_screenshot).with_name(
                        f'waiting_{wait_phase}{args.side}.bmp')
                    pygame.image.save(surface, str(wait_capture))
                    wait_screenshots[wait_phase] = str(wait_capture)
                if menu_sync.active:
                    next_caption = f'{base_caption} — {returning_label}'
                elif cable_wait and cable_wait['seconds'] >= 1.0:
                    next_caption = f'{base_caption} — {waiting_label}'
                else:
                    next_caption = base_caption
                if next_caption != displayed_caption:
                    pygame.display.set_caption(next_caption)
                    displayed_caption = next_caption
                now = time.monotonic()
                stamp = settings_stamp
                if now >= next_settings_check:
                    stamp = settings_path.stat().st_mtime_ns
                    next_settings_check = now + .25
                if stamp != settings_stamp:
                    updated = configparser.ConfigParser()
                    updated.read(args.settings, encoding='utf-8-sig')
                    settings = updated['Console'] if updated.has_section('Console') else {}
                    settings_stamp = stamp
                    audio.set_volume(0 if option('Muted') else max(0,min(100,option('Volume',100)))/100)
                    core.vulkan_smooth = bool(option('Smooth'))
                    core.vulkan_preserve_aspect = option('Aspect') != 2
                cable.check_role_timeout()
                exposed = False
                for event in pygame.event.get(pump=not bool(native_handle)):
                    if event.type == pygame.WINDOWEXPOSED:
                        exposed = True
                    if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                        stop.set()
                    elif event.type == pygame.WINDOWFOCUSLOST: focused.clear()
                    elif event.type == pygame.WINDOWFOCUSGAINED: focused.set()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                        fullscreen = not fullscreen
                        if actual_backend == 'vulkan' and window_handle is not None:
                            pygame.display.toggle_fullscreen()
                        else:
                            surface = pygame.display.set_mode((0, 0) if fullscreen else (960, 720), pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE)
                        exposed = True
                if link.error or cable.error:
                    raise RuntimeError(link.error or cable.error)
                present_video(exposed)
                if time.monotonic()-last_status > 1:
                    waits = sorted(cable.wait_ms)
                    status('connected', frames=core.frame,
                           gameplay_ticks=cable.gameplay, time_mismatches=cable.time_mismatches,
                           rng_mismatches=cable.rng_mismatches, audio_error=core.audio_error,
                           cable_exchanges=cable.exchanges, cable_bytes_sent=cable.bytes_sent,
                           cable_bytes_received=cable.bytes_received,
                           cable_waiting_for_peer=bool(cable_wait),
                           cable_wait_phase=(cable_wait['phase'] if cable_wait else None),
                           cable_wait_call=(f"0x{cable_wait['call']:08X}"
                                            if cable_wait and cable_wait['call'] is not None else None),
                           cable_wait_seconds=(round(cable_wait['seconds'], 2) if cable_wait else 0),
                           cable_wait_ms_p95=(waits[int((len(waits)-1)*.95)] if waits else None),
                           video_backend=actual_backend, video_adapter=video_adapter,
                           local_core_count=len(cores),
                           game_menu=(hex(core.word(0x89a0c)) if core else None),
                           game_input_calls=core.input_calls,
                           game_pressed_calls=core.pressed_calls,
                           role_waiting=cable.role_pending is not None,
                           role_agreed=cable.role_agreed,
                           role_round=cable.role_round,
                           video_frames_rendered=core.video_frames,
                           video_frames_presented=(core.video_frames_presented
                                                   if actual_backend == 'vulkan' else video_frames_presented),
                           one_console_per_pc=True)
                    last_status = time.monotonic()
                clock.tick(120)
            if errors: raise RuntimeError(errors[0])
            if qa_recording:
                if args.qa_screenshot:
                    core.screenshot(args.qa_screenshot)
                presented_frames = (core.video_frames_presented
                                    if actual_backend == 'vulkan' else video_frames_presented)
                with audio_stats_lock:
                    audio_report = dict(audio_stats)
                report = dict(completed=cable.gameplay==qa_target, hashes=qa_hashes,
                              gameplay_ticks=cable.gameplay, time_mismatches=cable.time_mismatches,
                              rng_mismatches=cable.rng_mismatches,
                              audio_error=audio_report['audio_error'] or core.audio_error,
                              architecture='one_console_per_pc',
                              local_core_count=len(cores),
                              p2p_cable_exchanges=cable.exchanges,
                              p2p_cable_bytes_sent=cable.bytes_sent,
                              p2p_cable_bytes_received=cable.bytes_received,
                              p2p_cable_wait_ms_mean=(sum(cable.wait_ms)/len(cable.wait_ms)
                                                       if cable.wait_ms else None),
                              p2p_cable_wait_ms_max=max(cable.wait_ms) if cable.wait_ms else None,
                              audio_started=audio_report['audio_started'],
                              audio_start_delay_ms=audio_report['audio_start_delay_ms'],
                              audio_underruns=audio_report['audio_underruns'],
                              audio_output_bytes=audio_report['audio_output_bytes'],
                              audio_output_chunks=audio_report['audio_output_chunks'],
                              pcm_generated_bytes=audio_report['pcm_generated_bytes'],
                              pcm_queue_dropped_bytes=audio_report['pcm_queue_dropped_bytes'],
                              pcm_stale_dropped_bytes=audio_report['pcm_stale_dropped_bytes'],
                              modal_ui_ticks=modal_ticks, modal_video_frames=modal_presented,
                              video_frames_rendered=core.video_frames,
                              video_frames_presented=presented_frames,
                              internal_resolution=resolution,
                              qa_screenshot=args.qa_screenshot,
                              video_backend=actual_backend,
                              video_adapter=video_adapter,
                              role_events=list(cable.role_events),
                              wait_screenshots=wait_screenshots,
                              menu_transitions=list(core.transitions),
                              input_events=list(qa_input_events),
                              rate=(qa_times[-1][1]-qa_times[0][1])/(qa_times[-1][0]-qa_times[0][0]) if len(qa_times)==2 else 0)
                Path(args.qa_report).write_text(json.dumps(report, indent=2))
    except Exception as exc:
        error_log = log_directory / 'ERROR_TM3_ONLINE.txt'
        error_log.write_text(traceback.format_exc() + '\nLast 120 seconds:\n' +
                             json.dumps(list(history), indent=2), encoding='utf-8')
        status('failed', error=str(exc), error_log=str(error_log))
        raise
    finally:
        stop.set()
        if cable: cable.stop()
        for thread in threads: thread.join(12)
        if not any(thread.is_alive() for thread in threads):
            for core in cores: core.close()
            if temporary_owner: temporary_owner.cleanup()
        audio_stop.set()
        if audio_thread: audio_thread.join(3)
        if dll_search_handle:
            dll_search_handle.close()
        if link: link.close()
        if native_handle: native_ui.tm3ui_detach(native_handle)
        pygame.quit()
        if not errors:
            try:
                current = json.loads(state_path.read_text())
                if current['state'] != 'failed': status('closed')
            except OSError: pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--epoch', type=int, required=True)
    parser.add_argument('--side', type=int, choices=(0,1), required=True)
    parser.add_argument('--assets', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--log-directory')
    parser.add_argument('--qa-fixture')
    parser.add_argument('--qa-report')
    parser.add_argument('--qa-screenshot')
    parser.add_argument('--qa-resolution', type=int, choices=(1, 2, 4), default=0,
                        help='Test-only internal render scale override, enabled only with --qa-fixture.')
    parser.add_argument('--qa-gameplay-ticks', type=int, default=600)
    parser.add_argument('--qa-delay-online-ms', type=int, default=0,
                        help='Test-only P2P delay for the first role response.')
    parser.add_argument('--qa-delay-vehicle-ms', type=int, default=0,
                        help='Test-only P2P delay for the first vehicle-select transfer.')
    args = parser.parse_args()
    if args.qa_resolution and not args.qa_fixture:
        parser.error('--qa-resolution requires --qa-fixture')
    if (args.qa_delay_online_ms or args.qa_delay_vehicle_ms) and not args.qa_fixture:
        parser.error('QA cable delays require --qa-fixture')
    if args.qa_gameplay_ticks < 1 or args.qa_gameplay_ticks > 100000:
        parser.error('--qa-gameplay-ticks must be between 1 and 100000')
    os.environ.update(TM3O_STANDARD_PS1='0', TM3O_DIAGNOSTICS='0')
    run(args)


if __name__ == '__main__': main()
