"""Desktop room browser for TM3. Run through ABRIR_SALAS.vbs on Windows."""
from __future__ import annotations

import ctypes
import configparser
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lobby_server import DISCOVERY, PORT, username, room_description, LocalDirectory
from relay_client import RelayBridge
from relay_protocol import loopback
from urllib.parse import urlsplit
import lobby_language as loc
from privacy import public_text, public_diagnostic
from ui_work import sync_tree
from directory_defaults import PUBLIC_DIRECTORY_URL

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA = (Path(os.environ['TM3_DATA_DIR']) if os.environ.get('TM3_DATA_DIR')
        else Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "TM3Online" / "Lobby")


def load_config():
    for path in (ROOT / "TM3Lobby.json", ROOT / "config/TM3Lobby.json", ROOT / "network/lobby_config.json"):
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
            if PUBLIC_DIRECTORY_URL and 'directory_url' not in config:
                config['directory_url'] = PUBLIC_DIRECTORY_URL
            return config
        except FileNotFoundError:
            continue
    return {'directory_url': PUBLIC_DIRECTORY_URL} if PUBLIC_DIRECTORY_URL else {}


def api(url, data=None):
    request = Request(url, data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
                      headers={"Content-Type": "application/json", "User-Agent": "TM3Lobby/3"})
    try:
        with urlopen(request, timeout=4) as response:
            return json.load(response)
    except HTTPError as exc:
        with exc:
            error = json.load(exc).get("error", "Error del directorio.")
        raise ValueError(error) from exc


def discover():
    """Collect LAN replies; return deterministic order when two PCs start together."""
    found = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(.25)
        sock.sendto(DISCOVERY, ("255.255.255.255", PORT))
        sock.sendto(DISCOVERY, ("127.0.0.1", PORT))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(256)
                prefix, port = data.decode().split()
                if prefix == "TM3_LOBBY_V1" and 0 < int(port) < 65536:
                    found.add(f"http://{address[0]}:{int(port)}")
            except (socket.timeout, ValueError, UnicodeError):
                continue
            except OSError as exc:
                # A probe to a closed UDP port can generate WSAECONNRESET on
                # Windows. No directory replying is normal: keep discovering.
                if getattr(exc, "winerror", None) == 10054 or exc.errno == 10054:
                    continue
                raise
    for url in sorted(found, key=lambda value: ("//127." in value, value)):
        try:
            info = api(url)
            if info.get("service") == "TM3Lobby" and info.get("version", 2) >= 2:
                return url
        except (OSError, ValueError):
            continue
    return None


def local_ip(url):
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, PORT))
        address = sock.getsockname()[0]
    if address.startswith("127."):
        candidates = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        address = next((row[4][0] for row in candidates if not row[4][0].startswith(("127.", "169.254."))), address)
    return address


def listening(pid, port):
    """Inspect owning PID without connecting to/consuming the game's single accept."""
    size = ctypes.c_ulong(0)
    fn = ctypes.windll.iphlpapi.GetExtendedTcpTable
    fn(None, ctypes.byref(size), False, socket.AF_INET, 5, 0)
    table = ctypes.create_string_buffer(size.value)
    if fn(table, ctypes.byref(size), False, socket.AF_INET, 5, 0):
        return False
    count = struct.unpack_from("<I", table.raw)[0]
    for i in range(count):
        state, _, rawport, _, _, owner = struct.unpack_from("<6I", table.raw, 4 + i * 24)
        if state == 2 and socket.ntohs(rawport & 0xffff) == port and owner == pid:
            return True
    return False


class Lobby:
    def __init__(self, root):
        self.root = root
        self.profile_path = DATA / "profile.json"
        self.profile = {}
        self.config = {}
        self.actions = queue.Queue()
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.token = None
        self.url = None
        self.room = None
        self.visible_rooms = {}
        self.room_window = None
        self.room_window_id = None
        self.room_leaving = False
        self.room_cancel = threading.Event()
        self.start_button = None
        self.leave_button = None
        self.process = None
        self.local_process = None
        self.owned_directory = None
        self.relay_bridge = None
        self.ice_peer = None
        self.ice_key = None
        self.directory_connection = None
        self.directory_info = {}
        self.last_error = ''
        self.last_ice_diagnostics = None
        self._next_latency_refresh = 0
        self.session_path = None
        self.return_event = None
        self.session_generation = None
        self.cancel_reported = False
        self.launch_lock = threading.Lock()
        self.handled = set()
        DATA.mkdir(parents=True, exist_ok=True)
        try:
            self.profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.config = load_config()
        runtime_exe = Path(self.config.get("runtime", {}).get("executable", "TM3Online_Lobby/runtime/TM3Online.exe"))
        self.language_path = (runtime_exe if runtime_exe.is_absolute() else ROOT / runtime_exe).parent / "TM3Console.ini"
        loc.language = "es" if ctypes.windll.kernel32.GetPrivateProfileIntW("Console", "Language", 0, str(self.language_path)) == 1 else "en"
        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.drain)
        root.after(150, self.connect)
        root.after(2500, lambda: self.check_release_update(automatic=True))

    def build_ui(self):
        self.root.title(loc.tr("TM3 Online | Salas"))
        self.root.geometry("820x600")
        self.root.minsize(760, 560)
        self.root.configure(bg="#101722")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#101722")
        style.configure("TLabel", background="#101722", foreground="#e4eaf4", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#69b7ff")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 6),
                        background="#263449", foreground="#eaf1ff", borderwidth=0, bordercolor="#263449")
        style.configure("Primary.TButton", background="#3979d3", foreground="#ffffff", font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#4b8ce6"), ("disabled", "#263449")])
        style.map("TButton", background=[("disabled", "#1c2a3b"), ("active", "#3d5b7d")],
                  foreground=[("disabled", "#a4b2c3"), ("active", "#ffffff")])
        style.configure("Connection.TLabel", foreground="#a5c8ef", font=("Segoe UI", 10))
        style.configure("Detail.TLabel", foreground="#ffcf91", font=("Segoe UI", 10))
        style.configure("TEntry", fieldbackground="#1b2635", foreground="#ffffff", padding=6)
        style.configure("Treeview", background="#182230", fieldbackground="#182230", foreground="#e4eaf4", rowheight=28, font=("Segoe UI", 10), borderwidth=0)
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"),
                        background="#223047", foreground="#a6bad5", padding=6, relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#3d5b7d")])
        style.map("Treeview", background=[("selected", "#285d8d")], foreground=[("selected", "#ffffff")])
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        loc.Label(header, text="TM3 ONLINE", style="Title.TLabel").pack(side="left")
        self.language_choice = ttk.Combobox(header, values=("English", "Español"), state="readonly", width=12)
        self.language_choice.set("English" if loc.language == "en" else "Español")
        self.language_choice.pack(side="right", pady=8)
        self.language_choice.bind("<<ComboboxSelected>>", self.change_language)
        name = self.profile.get("name")
        self.identity = loc.Label(frame, text=f"Bienvenido, {name}" if name else "Bienvenido a TM3 Online")
        self.identity.grid(row=1, column=0, sticky="w", pady=(5, 3))
        self.connection = loc.Label(frame, text="Buscando conexión...", style="Connection.TLabel")
        self.connection.grid(row=2, column=0, sticky="w", pady=(0, 10))
        self.instructions = loc.Label(frame, text="Dos PC por sala. Para probar 2+2, activa el segundo jugador en los mandos de cada PC.", wraplength=820)
        self.instructions.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self.table = ttk.Treeview(frame, columns=("description", "host", "players", "state"), show="headings", selectmode="browse", height=4)
        for col, title, width in (("description", "Descripción de sala", 300), ("host", "Anfitrión", 160), ("players", "Jugadores", 100), ("state", "Estado", 140)):
            self.table.heading(col, text=loc.tr(title), anchor="center" if col == "players" else "w")
            self.table.column(col, width=width, anchor="center" if col == "players" else "w", stretch=col == "description", minwidth=70)
        self.table.grid(row=4, column=0, sticky="nsew")
        self.table.bind("<Double-1>", lambda _: self.join())
        self.table.bind("<<TreeviewSelect>>", lambda _: self.update_join_button())
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="w", pady=8)
        self.create_button = loc.Button(buttons, text="Crear sala", command=self.create_room, style="Primary.TButton")
        self.join_button = loc.Button(buttons, text="Unirse", command=self.join)
        for button in (self.create_button, self.join_button):
            button.pack(side="left", padx=(0, 9))
            button.configure(state="disabled")
        self.local_button = loc.Button(buttons, text="Jugar local", command=self.play_local, style="Primary.TButton")
        self.local_button.pack(side="left", padx=(28, 0))
        self.members = loc.Label(frame, text="Todavía no estás en una sala.", wraplength=820)
        self.members.grid(row=6, column=0, sticky="ew")
        self.status = loc.Label(frame, text="Buscando salas automáticamente...", wraplength=820)
        self.status.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        self.latency_label = loc.Label(frame, text='', style='Connection.TLabel', wraplength=820)
        self.latency_label.grid(row=8, column=0, sticky='ew', pady=(5, 0))
        self.latency_label.grid_remove()
        self.error_detail = loc.Label(frame, text="", style="Detail.TLabel", wraplength=820)
        self.error_detail.grid(row=9, column=0, sticky="ew", pady=(5, 0))
        self.retry = loc.Button(frame, text="Reconectar", command=self.connect)
        self.retry.grid(row=10, column=0, sticky="w", pady=(12, 0))
        self.network_settings = loc.Button(frame, text="Conexión a Internet", command=self.configure_directory)
        if not self.config.get('system256', {}).get('enabled', False):
            self.network_settings.grid(row=10, column=0, sticky="e", pady=(12, 0))
        self.export_button = loc.Button(frame, text='Guardar diagnóstico', command=self.export_diagnostics)
        self.export_button.grid(row=10, column=0, sticky='w', padx=(160, 0), pady=(12, 0))
        def resize_text(event):
            for label in (self.instructions, self.members, self.status, self.latency_label, self.error_detail):
                label.configure(wraplength=max(300, event.width - 44))
        frame.bind("<Configure>", resize_text)

    def check_release_update(self, automatic=False):
        if getattr(self, '_release_checked', False): return
        self._release_checked = True
        self._checking_release = True
        def check():
            from release_updater import check_update
            try:
                current = (ROOT/'VERSION').read_text().strip()
                update = check_update(current)
                self.events.put(('release_update', (update, automatic)))
            except Exception as exc:
                if not automatic: self.events.put(('error', 'Actualización: ' + str(exc)))
            finally:
                self._checking_release = False
        threading.Thread(target=check, daemon=True).start()

    def apply_release_update(self, update):
        from update_window import UpdateWindow
        self.update_cache = DATA/'updates'
        self.install_root = ROOT
        self.update_window = UpdateWindow(self, update)

    def change_language(self, event=None):
        loc.language = "es" if self.language_choice.get() == "Español" else "en"
        self.language_path.parent.mkdir(parents=True, exist_ok=True)
        ctypes.windll.kernel32.WritePrivateProfileStringW("Console", "Language", "1" if loc.language == "es" else "0", str(self.language_path))
        def refresh(widget):
            if isinstance(widget, loc.Localized):
                widget.retranslate()
            for child in widget.winfo_children():
                refresh(child)
        refresh(self.root)
        self.root.title(loc.tr("TM3 Online | Salas"))
        for col, title in (("description", "Descripción de sala"), ("host", "Anfitrión"), ("players", "Jugadores"), ("state", "Estado")):
            self.table.heading(col, text=loc.tr(title))
        if getattr(self, "room_players", None) and self.room_players.winfo_exists():
            for col, title in (("seat", "Puesto"), ("name", "Jugador"), ("role", "Rol")):
                self.room_players.heading(col, text=loc.tr(title))

    def configure_emulator(self):
        """Edit the same per-PC INI consumed by local and SYSTEM256 play."""
        if ((self.process and self.process.poll() is None) or
                (self.local_process and self.local_process.poll() is None)):
            messagebox.showinfo("TM3 Online", "Cierra la partida antes de cambiar su configuración.", parent=self.root)
            return
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(self.language_path, encoding='utf-8-sig')
        if not config.has_section('Console'):
            config.add_section('Console')
        values = config['Console']
        window = tk.Toplevel(self.root)
        window.title("Configuración local del emulador")
        window.geometry('720x650'); window.minsize(620, 540)
        window.configure(bg='#101722'); window.transient(self.root); window.grab_set()
        tabs = ttk.Notebook(window); tabs.pack(fill='both', expand=True, padx=18, pady=18)
        video = ttk.Frame(tabs, padding=18); audio = ttk.Frame(tabs, padding=18)
        controls = ttk.Frame(tabs, padding=18)
        tabs.add(video, text='Vídeo'); tabs.add(audio, text='Audio'); tabs.add(controls, text='Controles')
        def integer(name, default=0):
            try: return int(values.get(name, default))
            except (TypeError, ValueError): return default
        resolution = tk.IntVar(value=integer('Resolution', 1))
        smooth = tk.BooleanVar(value=bool(integer('Smooth')))
        pgxp = tk.BooleanVar(value=bool(integer('PGXP')))
        ttk.Label(video, text='Resolución interna (1x es la opción estable recomendada)').pack(anchor='w')
        ttk.Combobox(video, textvariable=resolution, values=(1, 2, 4), state='readonly').pack(anchor='w', fill='x', pady=(4, 14))
        ttk.Checkbutton(video, text='Suavizado de imagen', variable=smooth).pack(anchor='w', pady=4)
        ttk.Checkbutton(video, text='PGXP (experimental)', variable=pgxp).pack(anchor='w', pady=4)
        ttk.Label(video, text='La imagen online conserva proporción 4:3. Los cambios se aplican en la próxima partida.', wraplength=620).pack(anchor='w', pady=(18, 0))

        muted = tk.BooleanVar(value=bool(integer('Muted')))
        volume = tk.IntVar(value=max(0, min(100, integer('Volume', 100))))
        current_device = values.get('AudioDeviceName', '')
        devices = []
        try:
            import pygame
            pygame.mixer.init()
            from pygame._sdl2.audio import get_audio_device_names
            devices = list(get_audio_device_names(False))
            pygame.mixer.quit()
        except Exception:
            pass
        choices = ['Predeterminado de Windows'] + devices
        if current_device and current_device not in choices:
            choices.append(current_device)
        device = tk.StringVar(value=current_device or choices[0])
        ttk.Label(audio, text='Dispositivo de salida de esta PC').pack(anchor='w')
        ttk.Combobox(audio, textvariable=device, values=choices, state='readonly').pack(anchor='w', fill='x', pady=(4, 14))
        ttk.Label(audio, text='Volumen').pack(anchor='w')
        ttk.Scale(audio, from_=0, to=100, variable=volume, orient='horizontal').pack(anchor='w', fill='x', pady=(4, 8))
        ttk.Checkbutton(audio, text='Silenciar', variable=muted).pack(anchor='w', pady=4)
        ttk.Label(audio, text='El audio es local e independiente: cada jugador elige su propio dispositivo.', wraplength=620).pack(anchor='w', pady=(18, 0))

        enabled = tk.BooleanVar(value=bool(integer('Controller', 1)))
        player2 = tk.BooleanVar(value=bool(integer('Player2Enabled')))
        controller_index = tk.IntVar(value=integer('ControllerIndex', 0))
        ttk.Checkbutton(controls, text='Activar mando/teclado del jugador 1', variable=enabled).pack(anchor='w')
        ttk.Label(controls, text='Índice del mando (0 es el primer mando conectado)').pack(anchor='w', pady=(8, 0))
        ttk.Combobox(controls, textvariable=controller_index, values=(0, 1, 2, 3), state='readonly').pack(anchor='w', fill='x', pady=(4, 8))
        ttk.Checkbutton(controls, text='Activar jugador 2 local (modo 2+2)', variable=player2).pack(anchor='w', pady=(0, 8))
        canvas = tk.Canvas(controls, bg='#101722', highlightthickness=0)
        scroll = ttk.Scrollbar(controls, orient='vertical', command=canvas.yview)
        mapping = ttk.Frame(canvas); mapping.columnconfigure(1, weight=1)
        canvas.create_window((0, 0), window=mapping, anchor='nw'); canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        mapping.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        names = ('Círculo','Cuadrado','Select','Start','Arriba','Abajo','Izquierda','Derecha',
                 'Cruz','Triángulo','L1','R1','L2','R2','L3','R3')
        key_values = [integer(f'Key{i}') for i in range(16)]
        pad_values = [integer(f'Pad{i}') for i in range(16)]
        key_buttons = []
        def capture(index, button):
            button.configure(text='Pulsa una tecla…')
            def chosen(event):
                key_values[index] = event.keycode
                button.configure(text=event.keysym)
                window.unbind('<Key>')
                return 'break'
            window.bind('<Key>', chosen)
            window.focus_force()
        for index, name in enumerate(names):
            ttk.Label(mapping, text=name).grid(row=index, column=0, sticky='w', padx=(0, 10), pady=3)
            button = ttk.Button(mapping, text=(f'VK {key_values[index]}' if key_values[index] else 'Sin tecla'))
            button.configure(command=lambda i=index, b=button: capture(i, b))
            button.grid(row=index, column=1, sticky='ew', pady=3); key_buttons.append(button)
            pad = ttk.Combobox(mapping, values=['Sin botón'] + [f'Botón {i}' for i in range(1, 25)], state='readonly', width=14)
            pad.current(pad_values[index] if 0 <= pad_values[index] <= 24 else 0)
            pad.grid(row=index, column=2, padx=(10, 0), pady=3); pad_values[index] = pad
        def save():
            updates = dict(Resolution=resolution.get(), Smooth=int(smooth.get()), PGXP=int(pgxp.get()),
                           Muted=int(muted.get()), Volume=int(round(volume.get())),
                           Controller=int(enabled.get()), ControllerIndex=controller_index.get(),
                           Player2Enabled=int(player2.get()))
            for key, value in updates.items(): values[key] = str(value)
            chosen_device = device.get()
            values['AudioDeviceName'] = '' if chosen_device == choices[0] else chosen_device
            for index in range(16):
                values[f'Key{index}'] = str(key_values[index])
                values[f'Pad{index}'] = str(pad_values[index].current())
            self.language_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.language_path.with_suffix('.ini.tmp')
            with temporary.open('w', encoding='utf-8-sig') as stream: config.write(stream)
            os.replace(temporary, self.language_path)
            self.status.configure(text='Configuración local guardada. Se aplicará en la próxima partida.')
            window.destroy()
        footer = ttk.Frame(window, padding=(18, 0, 18, 18)); footer.pack(fill='x')
        ttk.Button(footer, text='Cancelar', command=window.destroy).pack(side='right')
        ttk.Button(footer, text='Guardar', command=save, style='Primary.TButton').pack(side='right', padx=(0, 8))
    def connect(self):
        if self.token or getattr(self, "worker", None) and self.worker.is_alive():
            return
        if not self.profile.get("name"):
            name = simpledialog.askstring(loc.tr("Tu usuario"), loc.tr("Crea tu nombre de jugador (2 a 24 caracteres):"), parent=self.root)
            if name is None:
                return
            try:
                name, _ = username(name)
            except ValueError as exc:
                messagebox.showerror("Usuario", public_text(exc), parent=self.root)
                return
            self.profile = {"name": name, "secret": secrets.token_hex(32)}
        self.retry.configure(state="disabled")
        self.identity.configure(text=f"Bienvenido, {self.profile['name']}")
        self.connection.configure(text="Conectando al lobby...")
        self.error_detail.configure(text="")
        self.status.configure(text="Buscando el directorio y las salas...")
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def configure_directory(self):
        value = simpledialog.askstring(loc.tr("Conexión a Internet"),
            loc.tr("Dirección HTTPS del lobby público. Vacío para red local:"),
            initialvalue="", parent=self.root)
        if value is None:
            return
        value = value.strip()
        try:
            parsed = urlsplit(value)
            if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                          parsed.password or parsed.query or parsed.fragment or
                          (parsed.port is not None and not 0 < parsed.port < 65536) or
                          any(c.isspace() or ord(c) < 32 for c in value)):
                raise ValueError("Usa una dirección HTTPS válida para el lobby público.")
            updated = {**self.config}
            if value:
                updated["directory_url"] = value.rstrip("/")
            else:
                updated['directory_url'] = ''  # Explicit LAN choice overrides bundled defaults.
            path = ROOT / "TM3Lobby.json"
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
            self.config = updated
            self.status.configure(text="Conexión guardada. Vuelve a abrir el lobby para aplicarla.")
        except (OSError, ValueError) as exc:
            messagebox.showerror(loc.tr("Conexión a Internet"), loc.tr(str(exc)), parent=self.root)

    def action(self, op, **kwargs):
        if self.token:
            self.actions.put({"op": op, **kwargs})

    def create_room(self):
        if not self.token or self.room:
            return
        text = simpledialog.askstring(loc.tr("Crear sala"), loc.tr("Descripción de la sala (1 a 100 caracteres):"), parent=self.root)
        if text is None:
            return
        try:
            text = room_description(text)
        except ValueError as exc:
            messagebox.showerror("Descripción de sala", public_text(exc), parent=self.root)
            return
        self.action("create", description=text)

    def join(self):
        selected = self.table.selection()
        if self.room and selected and selected[0] == self.room["id"]:
            self.show_room()
            return
        if selected and not self.room and self.visible_rooms.get(selected[0], {}).get("joinable"):
            self.action("join", room=selected[0])

    def show_room(self):
        if self.room_window and self.room_window.winfo_exists():
            self.room_window.deiconify()
            self.room_window.lift()
            self.room_window.focus_set()

    def destroy_room_window(self):
        if self.room_window and self.room_window.winfo_exists():
            self.room_window.destroy()
        self.room_window = None
        self.room_window_id = None
        self.start_button = None
        self.leave_button = None
        self.room_leaving = False

    def leave_room(self):
        if self.room and not self.room_leaving:
            self.room_leaving = True
            self.room_cancel.set()
            self.start_button.configure(state="disabled")
            self.leave_button.configure(state="disabled")
            self.room_status.configure(text="Saliendo de la sala...")
            self.action("leave")

    def stop_room_process(self):
        """Only the Popen handle launched for this room; never search by game name."""
        self.close_relay()
        bridge = getattr(self, 'engine_bridge', None)
        if bridge:
            bridge.close()
            self.engine_bridge = None
        process = self.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            self.process = None

    def close_relay(self):
        bridge = getattr(self, "relay_bridge", None)
        if bridge:
            bridge.close()
            self.relay_bridge = None

    def close_ice(self):
        bridge = getattr(self, 'engine_bridge', None)
        if bridge:
            bridge.close()
            self.engine_bridge = None
        peer, self.ice_peer = self.ice_peer, None
        self.ice_key = None
        if peer:
            peer.close()
            self.last_ice_diagnostics = peer.snapshot()

    def export_diagnostics(self):
        def save():
            try:
                peer = self.ice_peer
                snapshot = peer.snapshot() if peer else self.last_ice_diagnostics
                room = self.room or {}
                report = dict(version='automatic_rooms_v1',
                    scope='shared_directory' if self.config.get('directory_url') or os.environ.get('TM3_LOBBY_URL') else 'lan',
                    connected_to_directory=bool(self.token), automatic_directory=self.directory_info.get('automatic_ice') == 1,
                    room_phase=room.get('phase'), room_error=room.get('error', ''), generation=room.get('generation'), players=len(room.get('players', [])),
                    connection_mode=room.get('connection_mode'), last_error=self.last_error, ice=snapshot)
                target = DATA / 'diagnostics' / ('rooms_' + str(time.time_ns()) + '.json')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(public_diagnostic(report), indent=2, ensure_ascii=False), encoding='utf-8')
                self.events.put(('diagnostic_saved', str(target)))
            except Exception as exc:
                self.events.put(('error', 'No se pudo guardar el diagnóstico: ' + type(exc).__name__))
        threading.Thread(target=save, daemon=True).start()

    def directory_call(self, data):
        if self.directory_connection:
            return self.directory_connection.request(data)
        return api(self.url, data)

    def negotiate_room(self, room):
        from p2p_session import P2PSession
        if self.config.get('system256', {}).get('enabled', False):
            from system256_bridge import System256Peer
            P2PSession = System256Peer
        key = (room['id'], room['generation'])
        if self.ice_key != key:
            self.close_ice()
            self.last_error = ''
            self.ice_peer = P2PSession(self.config.get('p2p', {}).get('ice_servers'))
            self.ice_key = key
        peer = self.ice_peer
        route = room.get('transport') or {}
        if peer.done.is_set():
            raise ValueError(peer.error or 'Se cerró la conexión automática.')
        if room['owner']:
            if peer.session is None:
                self.actions.put(dict(op='ice_offer', generation=room['generation'], code=peer.create_offer()))
            elif not peer.remote_applied and route.get('answer'):
                peer.accept_answer(route['answer'])
        elif peer.session is None and route.get('offer'):
            self.actions.put(dict(op='ice_answer', generation=room['generation'], code=peer.create_answer(route['offer'])))
        ready_key = (*key, 'ice_ready')
        if peer.connected.is_set() and ready_key not in self.handled:
            self.handled.add(ready_key)
            self.actions.put(dict(op='ice_ready', generation=room['generation']))

    def return_room_process(self):
        if getattr(self, 'engine_bridge', None):
            self.stop_room_process()
            return
        if self.session_state().get("state") == "returned":
            return
        if self.process is not None and self.process.poll() is None and self.return_event:
            ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(self.return_event))

    def session_state(self):
        try:
            return json.loads(self.session_path.read_text(encoding="utf-8")) if self.session_path else {}
        except (OSError, ValueError):
            return {}

    def close_process(self, process):
        if process is None or process.poll() is not None:
            return
        # Ask the exact owned emulator to exit first, so it can save its cards.
        if isinstance(process.pid, int):
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def visit(window, _):
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(window), ctypes.byref(pid))
                if pid.value == process.pid:
                    ctypes.windll.user32.PostMessageW(ctypes.c_void_p(window), 0x10, 0, 0)
                return True
            ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def send_chat(self):
        if self.room and not self.room_leaving:
            text = self.chat_input.get().strip()
            if text:
                if len(text) > 500:
                    self.room_status.configure(text="El mensaje puede tener hasta 500 caracteres.")
                else:
                    self.action("chat", text=text)
                    self.chat_input.delete(0, "end")
        return "break"

    def render_chat(self, messages):
        signature = tuple(message["id"] for message in messages)
        if signature == self.chat_signature:
            return
        self.chat_signature = signature
        follow = self.chat_log.yview()[1] >= .98
        position = self.chat_log.yview()[0]
        self.chat_log.configure(state="normal")
        self.chat_log.delete("1.0", "end")
        for message in messages:
            stamp = time.strftime("%H:%M", time.localtime(message["time"]))
            prefix = f"[{stamp}] " if message["kind"] == "system" else f"[{stamp}] {message['name']}: "
            self.chat_log.insert("end", prefix + message["text"] + "\n", "system" if message["kind"] == "system" else "text")
        self.chat_log.configure(state="disabled")
        if follow:
            self.chat_log.see("end")
        else:
            self.chat_log.yview_moveto(position)

    def sync_room_window(self):
        if not self.room:
            self.destroy_room_window()
            return
        room = self.room
        if not self.room_window or not self.room_window.winfo_exists() or self.room_window_id != room["id"]:
            self.destroy_room_window()
            self.room_window_id = room["id"]
            window = self.room_window = tk.Toplevel(self.root)
            window.withdraw()
            window.title(f"TM3 Online | {room.get('description', 'Sala de ' + room['host'])}")
            width, height = 680, 570
            self.root.update_idletasks()
            x = max(8, min(self.root.winfo_x() + 35, self.root.winfo_screenwidth() - width - 8))
            y = max(8, min(self.root.winfo_y() + 35, self.root.winfo_screenheight() - height - 55))
            window.geometry(f"{width}x{height}+{x}+{y}")
            window.minsize(620, 530)
            window.configure(bg="#101722")
            window.protocol("WM_DELETE_WINDOW", self.leave_room)
            frame = ttk.Frame(window, padding=14)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(7, weight=1)
            loc.Label(frame, text="TWISTED METAL III", style="Title.TLabel").grid(row=0, column=0, sticky="w")
            self.room_heading = loc.Label(frame)
            self.room_heading.grid(row=1, column=0, sticky="ew", pady=(10, 4))
            self.room_role = loc.Label(frame, style="Connection.TLabel")
            self.room_role.grid(row=2, column=0, sticky="w", pady=(0, 14))
            self.room_players = ttk.Treeview(frame, columns=("seat", "name", "role"), show="headings", height=2, selectmode="none")
            for col, heading, width in (("seat", "Puesto", 70), ("name", "Jugador", 270), ("role", "Rol", 170)):
                self.room_players.heading(col, text=loc.tr(heading), anchor="center" if col == "seat" else "w")
                self.room_players.column(col, width=width, anchor="center" if col == "seat" else "w", stretch=col == "name", minwidth=60)
            self.room_players.grid(row=3, column=0, sticky="ew")
            self.room_status = loc.Label(frame, wraplength=570)
            self.room_status.grid(row=4, column=0, sticky="ew", pady=(10, 8))
            self.room_latency = loc.Label(frame, wraplength=570, style='Connection.TLabel')
            self.room_latency.grid(row=5, column=0, sticky='ew', pady=(0, 8))
            loc.Label(frame, text="Chat de la sala").grid(row=6, column=0, sticky="w", pady=(0, 6))
            chat_frame = ttk.Frame(frame)
            chat_frame.grid(row=7, column=0, sticky="nsew")
            chat_frame.columnconfigure(0, weight=1)
            chat_frame.rowconfigure(0, weight=1)
            self.chat_log = tk.Text(chat_frame, height=5, width=1, wrap="word", state="disabled", font=("Segoe UI", 10),
                                    bg="#1b2635", fg="#e4eaf4", relief="flat", padx=10, pady=8, selectbackground="#285d8d")
            self.chat_log.grid(row=0, column=0, sticky="nsew")
            self.chat_log.tag_configure("system", foreground="#a5c8ef")
            self.chat_log.tag_configure("text", foreground="#ffffff")
            scroll = ttk.Scrollbar(chat_frame, command=self.chat_log.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            self.chat_log.configure(yscrollcommand=scroll.set)
            self.chat_signature = None
            compose = ttk.Frame(frame)
            compose.grid(row=8, column=0, sticky="ew", pady=(8, 12))
            compose.columnconfigure(0, weight=1)
            self.chat_input = ttk.Entry(compose, font=("Segoe UI", 10))
            self.chat_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            self.chat_input.bind("<Return>", lambda _: self.send_chat())
            self.chat_send = loc.Button(compose, text="Enviar", command=self.send_chat)
            self.chat_send.grid(row=0, column=1)
            self.room_note = loc.Label(frame, text="El lobby general sigue abierto para consultar todas las salas.", wraplength=570, style="Connection.TLabel")
            self.room_note.grid(row=9, column=0, sticky="ew", pady=(0, 12))
            buttons = ttk.Frame(frame)
            buttons.grid(row=10, column=0, sticky="ew")
            buttons.columnconfigure(0, weight=1)
            self.leave_button = loc.Button(buttons, command=self.leave_room)
            self.leave_button.grid(row=0, column=0, sticky="w")
            self.start_button = loc.Button(buttons, text="START", command=lambda: self.action("start"))
            self.start_button.grid(row=0, column=1, sticky="e")
            def resize_room(event):
                width = max(300, event.width - 44)
                for label in (self.room_heading, self.room_status, self.room_latency, self.room_note):
                    label.configure(wraplength=width)
            frame.bind("<Configure>", resize_room)
            self.show_room()
        count = len(room["players"])
        self.room_heading.configure(text=f"{room.get('description', 'Sala de ' + room['host'])}\nAnfitrión: {room['host']}  ·  {count}/{room['capacity']} jugadores")
        self.room_role.configure(text="Eres el anfitrión · Tú inicias la partida" if room["owner"] else "Eres el invitado · El anfitrión inicia la partida")
        self.room_note.configure(text="Conexión por relay de Internet. No necesitas abrir puertos del router."
            if room.get("connection_mode") == "relay" else
            "Conexión automática entre las PC. El directorio no transmite la partida."
            if room.get('connection_mode') == 'ice' else "El lobby general sigue abierto para consultar todas las salas.")
        rows = []
        for seat in range(room["capacity"]):
            occupied = seat < count
            name = room["players"][seat] if occupied else loc.tr("Esperando jugador...")
            role = ("Anfitrión" if seat == 0 else "Invitado") if occupied else "Disponible"
            rows.append((str(seat), (seat + 1, name, loc.tr(role))))
        sync_tree(self.room_players, rows)
        can_start = room["owner"] and count == 2 and room["phase"] == "waiting" and not self.room_leaving
        self.start_button.configure(state="normal" if can_start else "disabled")
        if room["owner"]:
            self.start_button.grid()
        else:
            self.start_button.grid_remove()
        self.leave_button.configure(text="Cerrar sala" if room["owner"] else "Salir de la sala", state="disabled" if self.room_leaving else "normal")
        text = {"connect": "Conectando las PC automáticamente... No necesitas copiar códigos.", "prepare": "Comprobando los archivos de ambos jugadores...", "host": "Abriendo el juego del anfitrión...",
                "client": "Abriendo el juego del invitado...", "playing": "Se inició la apertura de ambos juegos."}.get(room["phase"])
        if text is None:
            text = "Espera a que se una otro jugador." if count < 2 else (
                "Los dos jugadores están en la sala. Pulsa START para abrir ambos juegos." if room["owner"] else "Ya estás en la sala. Espera a que el anfitrión pulse START.")
        self.room_status.configure(text="Saliendo de la sala..." if self.room_leaving else room["error"] or text)
        self.chat_input.configure(state="disabled" if self.room_leaving else "normal")
        self.chat_send.configure(state="disabled" if self.room_leaving else "normal")
        self.render_chat(room.get("chat", []))
        self.refresh_latency()

    def refresh_latency(self):
        if not self.room:
            self.latency_label.grid_remove()
            return
        text = 'Ping entre PC: no disponible en esta conexión.'
        if self.room.get('connection_mode') == 'ice':
            peer = self.ice_peer
            stats = peer.latency_snapshot() if peer else {}
            text = 'Ping entre PC: se medirá al conectar la partida.'
            if peer:
                if not stats.get('connected'):
                    text = 'Ping entre PC: esperando conexión.'
                elif not stats.get('samples'):
                    text = 'Ping entre PC: midiendo...'
                elif stats.get('stale'):
                    text = 'Ping entre PC: sin muestra reciente.'
                else:
                    text = (f"Ping entre PC (RTT): {stats['rtt_ms']:.1f} ms · "
                            f"Promedio: {stats['average_ms']:.1f} ms · "
                            f"Variación: {stats['variation_ms']:.1f} ms")
        self.latency_label.configure(text=text)
        self.latency_label.grid()
        if self.room_window and self.room_window.winfo_exists():
            self.room_latency.configure(text=text)

    def update_join_button(self):
        selected = self.table.selection()
        available = self.token and not self.room and selected and self.visible_rooms.get(selected[0], {}).get("joinable")
        self.join_button.configure(state="normal" if available else "disabled")

    def find_directory(self):
        configured = os.environ.get("TM3_LOBBY_URL") or self.config.get("directory_url")
        if configured:
            parsed = urlsplit(configured)
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Usa una dirección HTTPS válida para el lobby público.')
            if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback(parsed.hostname)):
                raise ValueError('El directorio de Internet requiere HTTPS para proteger la sesion.')
            info = api(configured)
            self.directory_info = info
            if info.get("service") != "TM3Lobby":
                raise ValueError("El directorio configurado no es un lobby TM3.")
            if info.get("version", 1) < 2:
                raise ValueError("Actualiza TM3Lobby en ambas PC antes de iniciar la partida.")
            if info.get("relay_protocol") and urlsplit(configured).scheme != "https" and not loopback(urlsplit(configured).hostname):
                raise ValueError("El directorio de Internet requiere HTTPS para proteger la sesion.")
            return configured
        found = discover()
        if found:
            return found
        if self.stop.is_set():
            raise ValueError("Cerrando.")
        try:
            self.owned_directory = LocalDirectory(DATA / "users.sqlite3")
        except OSError:
            pass  # Another launcher may have won the bind race; discover it.
        for _ in range(3):
            if self.stop.wait(.5):
                raise ValueError("Cerrando.")
            found = discover()
            if found:
                return found
        raise ValueError("No se pudo abrir el lobby local. Revisa el puerto 27890 y el firewall.")

    def run(self):
        previous_room = None
        try:
            self.url = self.find_directory()
            if self.directory_info.get('websocket_rpc') == 1:
                from worker_directory import WorkerDirectory
                self.directory_connection = WorkerDirectory(self.url)
            login = {'op': 'login', 'name': self.profile['name'], 'automatic_ice': 1}
            if not self.directory_connection:
                login.update(**self.profile, lan=local_ip(self.url), relay_protocol=1)
            result = self.directory_call(login)
            self.token = result["token"]
            self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
            self.events.put(("connected", None))
            while not self.stop.is_set():
                try:
                    command = self.actions.get(timeout=1)
                except queue.Empty:
                    command = {"op": "poll"}
                try:
                    if command["op"] == "leave":
                        self.return_room_process()
                    result = self.directory_call({**command, "token": self.token})
                    next_room = result.get("room")
                    if previous_room and (not next_room or len(next_room["players"]) < len(previous_room["players"])):
                        self.return_room_process()
                        self.close_relay()
                        self.close_ice()
                    if next_room and previous_room and previous_room["phase"] != "waiting" and next_room["phase"] == "waiting":
                        self.return_room_process()
                        if previous_room['phase'] != 'playing':
                            self.close_ice()
                    if next_room and next_room["phase"] == "playing" and not self.cancel_reported:
                        state = self.session_state().get("state")
                        if state in ("returned", "closed", "failed") or (self.process is not None and self.process.poll() is not None):
                            self.cancel_reported = True
                            self.actions.put({"op": "cancel", "generation": next_room["generation"]})
                    if next_room and (not previous_room or next_room["id"] != previous_room["id"]):
                        self.room_cancel.clear()
                        self.handled.clear()
                    previous_room = next_room
                    bridge = self.relay_bridge
                    if (bridge and bridge.done.is_set() and bridge.error and next_room and
                            next_room["phase"] == "playing" and not self.cancel_reported):
                        self.cancel_reported = True
                        self.events.put(("error", bridge.error))
                        self.actions.put({"op": "cancel", "generation": next_room["generation"]})
                    peer = self.ice_peer
                    if (peer and peer.done.is_set() and next_room and next_room['phase'] == 'playing' and not self.cancel_reported):
                        self.cancel_reported = True
                        self.return_room_process()
                        self.events.put(('error', peer.error or 'Se perdió la conexión entre las PC.'))
                        self.actions.put(dict(op='cancel', generation=next_room['generation']))
                    self.events.put(("state", result))
                    self.advance(next_room)
                except ValueError as exc:
                    if "Sesion vencida" in str(exc):
                        raise
                    self.events.put(("error", str(exc)))
        except Exception as exc:
            self.return_room_process()
            self.events.put(("disconnected", str(exc)))
        finally:
            self.close_relay()
            self.close_ice()
            if self.token:
                try:
                    self.directory_call({"op": "logout", "token": self.token})
                except Exception:
                    pass
            self.token = None
            if self.directory_connection:
                self.directory_connection.close()
                self.directory_connection = None

    def runtime(self):
        runtime = self.config.get("runtime", {})
        def path(key, default):
            value = Path(runtime.get(key, default))
            return value if value.is_absolute() else ROOT / value
        exe = path("executable", "frontend/build/Release/TM3Online.exe")
        core = path("core", "frontend/build/Release/cores/beetle_psx_libretro.dll")
        game = path("game", "frontend/build/Release/game/TM3 Online.cue")
        for item in (exe, core, game):
            if not item.is_file():
                raise ValueError(f"Falta el archivo: {item}")
        if game.suffix.lower() == ".cue":
            for filename in re.findall(r'^\s*FILE\s+"([^"]+)"', game.read_text(encoding="utf-8-sig"), re.MULTILINE | re.IGNORECASE):
                if not (game.parent / filename).is_file():
                    raise ValueError(f"Falta una pista del disco: {filename}")
        if "oscar" in exe.stem.lower() or "sofia" in exe.stem.lower():
            raise ValueError("Configura el ejecutable neutro TM3Online.exe para poder elegir anfitrion automaticamente.")
        if any(process is not None and process.poll() is None
               for process in (self.process, getattr(self, "local_process", None))):
            raise ValueError("Tu juego sigue abierto. Cierralo antes de iniciar otra partida.")
        return exe, core, game

    def game_environment(self, label):
        # Do not inherit capture/probe variables from a development terminal.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("TM3O_")}
        runtime = self.config.get("runtime", {})
        environment.update(runtime.get("environment", {}))
        log_files = runtime.get("log_files", {})
        if log_files and runtime.get("diagnostics", False):
            log_dir = DATA / "runs" / f"{time.time_ns()}_{label}"
            log_dir.mkdir(parents=True)
            for key, filename in log_files.items():
                environment[key] = str(log_dir / Path(filename).name)
        return environment

    def launch_game(self, slot, mode):
        with self.launch_lock:
            exe, core, game = self.runtime()
            if getattr(sys, "frozen", False):
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                control = ["--parent-pid", str(os.getpid())]
                if mode:
                    sessions = DATA / "sessions"
                    sessions.mkdir(parents=True, exist_ok=True)
                    key = secrets.token_hex(16)
                    if self.session_path:
                        self.session_path.unlink(missing_ok=True)
                    self.session_path = sessions / (key + ".json")
                    if self.return_event:
                        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.return_event))
                    create = ctypes.windll.kernel32.CreateEventW
                    create.restype = ctypes.c_void_p
                    name = "Local\\TM3Return_" + key
                    self.return_event = create(None, True, False, name)
                    if not self.return_event:
                        raise OSError("Could not create game session control")
                    control += ["--session-state", str(self.session_path), "--return-menu-event", name]
                    self.cancel_reported = False
                process = subprocess.Popen([str(exe), "--windowed", "--core", str(core), "--game", str(game), *control,
                                         "--save-slot", slot, *mode], cwd=exe.parent,
                                        env=self.game_environment(slot),
                                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                if slot == "lobby_local":
                    self.local_process = process
                else:
                    self.process = process
                return process
            finally:
                if getattr(sys, "frozen", False):
                    ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)

    def play_local(self):
        try:
            if self.room or not self.actions.empty():
                raise ValueError("Sal de la sala o espera a que termine la solicitud antes de jugar local.")
            self.local_process = self.launch_game("lobby_local", [])
            self.status.configure(text="Juego local abierto. No necesita otra computadora ni una sala.")
        except Exception as exc:
            messagebox.showerror("Juego local", public_text(exc), parent=self.root)

    def advance(self, room):
        if not room or self.room_cancel.is_set():
            return
        phase = room["phase"]
        if room.get('connection_mode') == 'ice' and phase == 'connect':
            try:
                self.negotiate_room(room)
            except Exception as exc:
                key = (room['id'], room['generation'], 'ice_failed')
                if key not in self.handled:
                    self.handled.add(key)
                    self.close_ice()
                    self.actions.put(dict(op='failed', generation=room['generation'], error=str(exc)))
            return
        key = (room["id"], room["generation"], phase)
        relevant = phase == "prepare" or phase == "host" and room["owner"] or phase == "client" and not room["owner"]
        if not relevant or key in self.handled:
            return
        self.handled.add(key)
        generation = room["generation"]
        try:
            if self.config.get('system256', {}).get('enabled', False):
                self.advance_system256(room)
                return
            if phase == "prepare":
                self.close_relay()
                if room.get('connection_mode') == 'ice':
                    if not self.ice_peer or not self.ice_peer.connected.is_set():
                        raise ValueError('La conexión automática todavía no está lista.')
                    self.ice_peer.detach_game()
            if phase == "prepare" and self.process is not None and self.session_state().get("state") in ("returned", "closed", "failed"):
                self.close_process(self.process)
                self.process = None
            exe, core, game = self.runtime()
            if phase == "prepare":
                if room["owner"]:
                    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                        with socket.socket(socket.AF_INET, kind) as probe:
                            probe.bind(("0.0.0.0", 27888))
                op = "ready"
            else:
                mode = ["--host", "27888"] if room["owner"] else ["--join", f"{room['address']}:27888"]
                route = room.get("transport")
                ice = room.get('connection_mode') == 'ice'
                if room.get("connection_mode") == "relay" and not route:
                    raise ValueError("Falta la credencial de conexion del relay. Vuelve a iniciar la sala.")
                if ice and not room['owner']:
                    port = self.ice_peer.attach_game(generation=generation)
                    mode = ['--join', f'127.0.0.1:{port}']
                elif route and not room["owner"]:
                    self.relay_bridge = RelayBridge(route)
                    self.relay_bridge.start(self.room_cancel)
                    mode = ["--join", f"127.0.0.1:{self.relay_bridge.local_port}"]
                self.process = self.launch_game("lobby_host" if room["owner"] else "lobby_client", mode)
                if self.room_cancel.is_set():
                    self.stop_room_process()
                    return
                if room["owner"]:
                    deadline = time.monotonic() + 8
                    while not listening(self.process.pid, 27888):
                        if self.room_cancel.is_set():
                            self.stop_room_process()
                            return
                        if self.process.poll() is not None or time.monotonic() >= deadline:
                            raise ValueError("El juego anfitrion no abrio su servidor TCP/UDP.")
                        if self.stop.wait(.1):
                            return
                    if ice:
                        self.ice_peer.attach_game(27888, generation=generation)
                    elif route:
                        self.relay_bridge = RelayBridge(route, host_port=27888)
                        self.relay_bridge.start(self.room_cancel)
                    op = "host_started"
                else:
                    deadline = time.monotonic() + 18
                    while self.session_state().get("state") != "connected":
                        if self.stop.wait(.1) or self.room_cancel.is_set():
                            return
                        if self.relay_bridge and self.relay_bridge.done.is_set():
                            raise ValueError(self.relay_bridge.error or "El relay cerro la conexion.")
                        if self.process.poll() is not None or self.session_state().get("state") == "failed" or time.monotonic() >= deadline:
                            self.return_room_process()
                            raise ValueError("No se confirmó la conexión del juego. Revisa la IP del anfitrión y TCP/UDP 27888 en ambas PC.")
                    op = "client_started"
            self.actions.put({"op": op, "generation": generation})
        except Exception as exc:
            self.return_room_process()
            self.close_relay()
            self.close_ice()
            self.actions.put({"op": "failed", "generation": generation, "error": str(exc)})

    def advance_system256(self, room):
        from system256_bridge import EngineBridge
        generation = room['generation']
        if room.get('connection_mode') != 'ice':
            raise ValueError('El motor SYSTEM256 requiere la conexión automática a Internet.')
        if room['phase'] == 'prepare':
            self.stop_room_process()
            peer = self.ice_peer
            if not peer or not peer.connected.is_set():
                raise ValueError('La conexión ICE todavía no está disponible.')
            bridge = EngineBridge(peer, generation)
            self.engine_bridge = bridge
            assets = ROOT / self.config['system256'].get('assets', 'runtime/system256')
            if getattr(sys, 'frozen', False):
                if assets.resolve() != (ROOT / 'runtime/system256').resolve():
                    raise ValueError('La ruta del motor no corresponde al paquete actual.')
                release = json.loads((ROOT / 'RELEASE_FILES.json').read_text(encoding='utf-8'))
                for name, expected in release['system256'].items():
                    path = assets / name
                    if path.parent.resolve() != assets.resolve():
                        raise ValueError('Ruta de archivo del motor inválida.')
                    with path.open('rb') as stream:
                        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if actual != expected:
                        raise ValueError('Archivo antiguo o modificado: ' + name + '. Extrae el paquete actualizado completo.')
            for name in ('TM3_SYSTEM256.bin', 'TM3_SYSTEM256.cue', 'beetle_psx_system256.dll'):
                if not (assets / name).is_file(): raise ValueError('Falta SYSTEM256: ' + name)
            sessions = DATA / 'sessions'; sessions.mkdir(parents=True, exist_ok=True)
            self.session_path = sessions / ('system256_' + secrets.token_hex(12) + '.json')
            arguments = ['--port', str(bridge.port), '--key', bridge.key.hex(), '--epoch', str(bridge.epoch),
                         '--side', '0' if room['owner'] else '1',
                         '--assets', str(assets), '--settings', str(self.language_path),
                         '--state', str(self.session_path)]
            arguments += ['--log-directory', str(ROOT)]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--system256', *arguments]
            else:
                command = [sys.executable, str(ROOT/'network/system256_runtime.py'), *arguments]
            environment = self.game_environment('system256')
            environment['PYTHONPATH'] = str(ROOT/'256mb system/src') + os.pathsep + environment.get('PYTHONPATH', '')
            self.process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            self.cancel_reported = False
            # Both launch during prepare. Do not wait for the other PC here:
            # the directory must first receive both ready acknowledgements.
            self.actions.put(dict(op='ready', generation=generation))
        else:
            deadline = time.monotonic() + 65
            while self.session_state().get('state') != 'connected':
                if self.room_cancel.is_set() or self.stop.is_set():
                    self.stop_room_process(); return
                state = self.session_state()
                if state.get('state') == 'failed': raise ValueError(state.get('error', 'Falló SYSTEM256.'))
                if not self.process or self.process.poll() is not None:
                    raise ValueError('El motor SYSTEM256 se cerró durante el arranque.')
                if time.monotonic() > deadline: raise ValueError('La otra PC no inició SYSTEM256 a tiempo.')
                self.stop.wait(.1)
            self.actions.put(dict(op='host_started' if room['owner'] else 'client_started', generation=generation))

    def drain(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "connected":
                    self.identity.configure(text=f"Bienvenido, {self.profile['name']}")
                    configured = os.environ.get("TM3_LOBBY_URL") or self.config.get("directory_url")
                    self.connection.configure(text="Conectado" if configured else "Conectado al lobby de la red local")
                    self.error_detail.configure(text='' if configured else 'Modo LAN: solo salas de esta red. El directorio de Internet todavía no está configurado.')
                elif kind == "disconnected":
                    data = public_text(data)
                    self.last_error = data
                    self.status.configure(text="No se pudo conectar al lobby. Pulsa Reconectar para volver a buscar.")
                    self.connection.configure(text="Sin conexión")
                    self.error_detail.configure(text=f"Detalle del error: {data}")
                    self.room = None
                    self.destroy_room_window()
                    for button in (self.create_button, self.join_button):
                        button.configure(state="disabled")
                    self.retry.configure(state="normal")
                    # A conflicting registration can be corrected without losing a valid saved identity.
                    if "usuario ya existe" in data or "usuario ya esta conectado" in data:
                        self.profile = {}
                        self.retry.configure(text="Elegir otro usuario")
                    else:
                        self.retry.configure(text="Reconectar")
                elif kind == "error":
                    data = public_text(data)
                    self.last_error = data
                    self.status.configure(text=data)
                    if self.room_window:
                        self.room_leaving = False
                        self.sync_room_window()
                        self.room_status.configure(text=data)
                elif kind == "state":
                    self.render(data)
                elif kind == 'diagnostic_saved':
                    self.status.configure(text=loc.tr('Diagnóstico guardado: ') + data)
                elif kind == 'release_update':
                    update, automatic = data
                    if update: self.apply_release_update(update)
                    elif not automatic: messagebox.showinfo('TM3 Online', 'Ya tienes la última versión.', parent=self.root)
                elif kind == 'release_progress':
                    if getattr(self, 'update_window', None): self.update_window.progress(*data)
                elif kind == 'release_downloaded':
                    if getattr(self, 'update_window', None): self.update_window.ready(data)
                elif kind == 'release_failed':
                    if getattr(self, 'update_window', None): self.update_window.failed(data)
        except queue.Empty:
            pass
        if time.monotonic() >= self._next_latency_refresh:
            self._next_latency_refresh = time.monotonic() + .5
            self.refresh_latency()
        self.root.after(80, self.drain)

    def render(self, data):
        self.visible_rooms = {room["id"]: room for room in data["rooms"]}
        rows = []
        labels = {"waiting": "En espera", "connect": "Conectando PC", "prepare": "Preparando", "host": "Abriendo anfitrion", "client": "Abriendo invitado", "playing": "Partida iniciada"}
        for room in data["rooms"]:
            state = "Llena" if room["phase"] == "waiting" and len(room["players"]) == room["capacity"] else labels[room["phase"]]
            rows.append((room['id'], (room.get("description", "Sala de " + room["host"]), room["host"], f"{len(room['players'])}/{room['capacity']}", loc.tr(state))))
        sync_tree(self.table, rows)
        self.room = data["room"]
        self.local_button.configure(state="disabled" if self.room else "normal")
        self.create_button.configure(state="disabled" if self.room else "normal")
        self.update_join_button()
        self.sync_room_window()
        self.refresh_latency()
        if self.room:
            self.members.configure(text=f"Estás en la sala de {self.room['host']}. Su ventana está abierta.")
            text = labels[self.room["phase"]]
            if self.room["phase"] == "waiting":
                text = "Espera al otro jugador." if len(self.room["players"]) < 2 else "El anfitrion puede pulsar START."
            self.status.configure(text=self.room["error"] or text)
        else:
            self.members.configure(text="Todavía no estás en una sala.")
            self.status.configure(text="No hay salas creadas. Pulsa Crear sala para ser anfitrión." if not data["rooms"] else "Selecciona una sala disponible y pulsa Unirse. La lista se actualiza automáticamente.")

    def close(self):
        if getattr(self, 'update_window', None): self.update_window.cancelled.set()
        self.stop.set()
        self.room_cancel.set()
        self.close_ice()
        self.close_relay()
        worker = getattr(self, "worker", None)
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=5)
        with self.launch_lock:
            self.close_process(self.process)
            self.close_process(self.local_process)
            self.process = self.local_process = None
        if self.owned_directory:
            self.owned_directory.close()
            self.owned_directory = None
        if self.return_event:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.return_event))
            self.return_event = None
        if self.session_path:
            self.session_path.unlink(missing_ok=True)
        self.root.destroy()


def main():
    app = tk.Tk()
    try:
        Lobby(app)
        app.mainloop()
    except Exception as exc:
        messagebox.showerror("TM3 Online", public_text(exc), parent=app)


if __name__ == "__main__":
    main()
