"""Manual ICE invitation UI, independent of LAN/public directory discovery."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import lobby_language as loc
from p2p_game import P2PGame
from p2p_session import P2PSession


class P2PWindow:
    def __init__(self, owner, data_path, listening):
        self.owner, self.data_path, self.listening = owner, data_path, listening
        self.peer = self.game = None
        self.host = None
        self.busy = False
        self.closed = False
        self.last_ui_error = ''
        self.jobs = queue.Queue()
        self.window = tk.Toplevel(owner.root)
        self.window.title(loc.tr('TM3 Online | Conexión P2P'))
        self.window.geometry('860x720')
        self.window.minsize(760, 660)
        self.window.configure(bg='#101722')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        frame.rowconfigure(6, weight=1)
        loc.Label(frame, text='P2P · Conectar dos PC', style='Title.TLabel').grid(row=0, sticky='w')
        loc.Label(frame, text='1. El anfitrión crea y envía su invitación.\n2. El invitado la pega, genera una respuesta y la devuelve.\n3. El anfitrión aplica la respuesta. Cuando conecte, pulsa START.',
                  wraplength=780).grid(row=1, sticky='ew', pady=10)
        actions = ttk.Frame(frame)
        actions.grid(row=2, sticky='w', pady=(0, 8))
        self.offer_button = loc.Button(actions, text='Crear invitación', command=self.offer)
        self.answer_button = loc.Button(actions, text='Responder invitación', command=self.answer)
        self.accept_button = loc.Button(actions, text='Aplicar respuesta', command=self.accept)
        for widget in (self.offer_button, self.answer_button, self.accept_button):
            widget.pack(side='left', padx=(0, 8))
        loc.Label(frame, text='Pega aquí el código que recibiste:').grid(row=3, sticky='w')
        self.input = tk.Text(frame, height=4, wrap='char', font=('Consolas', 10), bg='#1b2635', fg='#e4eaf4', insertbackground='white')
        self.input.grid(row=4, sticky='nsew', pady=(5, 10))
        loc.Label(frame, text='Tu código para enviar al otro equipo:').grid(row=5, sticky='w')
        self.output = tk.Text(frame, height=4, wrap='char', font=('Consolas', 10), state='disabled', bg='#1b2635', fg='#e4eaf4')
        self.output.grid(row=6, sticky='nsew', pady=5)
        self.copy_button = loc.Button(frame, text='Copiar mi código', command=self.copy)
        self.copy_button.grid(row=7, sticky='w', pady=(0, 10))
        self.status = loc.Label(frame, text='Listo para crear o responder una invitación.', wraplength=780)
        self.status.grid(row=8, sticky='ew', pady=5)
        self.detail = loc.Label(frame, text='Tienes 30 minutos para intercambiar códigos. No hace falta sincronizar los relojes.', wraplength=780, style='Connection.TLabel')
        self.detail.grid(row=9, sticky='ew', pady=5)
        bottom = ttk.Frame(frame)
        bottom.grid(row=10, sticky='ew', pady=(10, 0))
        self.start_button = loc.Button(bottom, text='START', command=self.start_game)
        self.cancel_button = loc.Button(bottom, text='Volver al menú', command=self.owner.return_room_process)
        self.export_button = loc.Button(bottom, text='Guardar diagnóstico', command=self.export)
        self.close_button = loc.Button(bottom, text='Cerrar conexión', command=self.close)
        for widget in (self.start_button, self.cancel_button, self.export_button, self.close_button):
            widget.pack(side='left', padx=(0, 8))
        self.refresh()
        self.timer = self.window.after(100, self.poll)

    def refresh(self):
        connected = self.peer and self.peer.connected.is_set()
        self.offer_button.configure(state='normal' if not self.busy and self.peer is None else 'disabled')
        self.answer_button.configure(state='normal' if not self.busy and self.peer is None else 'disabled')
        self.accept_button.configure(state='normal' if not self.busy and self.host and self.peer and not self.peer.remote_applied and not self.peer.done.is_set() else 'disabled')
        self.start_button.configure(state='normal' if connected and self.host and self.game and self.game.state == 'waiting' else 'disabled')
        self.cancel_button.configure(state='normal' if connected and self.owner.process is not None else 'disabled')
        self.export_button.configure(state='normal' if self.peer else 'disabled')

    def job(self, function, kind):
        if self.busy:
            return
        self.busy = True
        self.status.configure(text='Buscando rutas ICE y dirección pública...')
        self.refresh()
        def work():
            try:
                self.jobs.put((kind, function()))
            except Exception as exc:
                self.jobs.put(('error', dict(source=kind, message=str(exc))))
            finally:
                if self.closed and self.peer:
                    self.peer.close()
        threading.Thread(target=work, name='TM3ICESignaling', daemon=True).start()

    def make_peer(self):
        self.peer = P2PSession(self.owner.config.get('p2p', {}).get('ice_servers'))
        return self.peer

    def offer(self):
        if self.peer is not None:
            return
        self.host = True
        self.job(lambda: self.make_peer().create_offer(), 'offer')

    def answer(self):
        if self.peer is not None:
            return
        code = self.input.get('1.0', 'end').strip()
        self.host = False
        self.job(lambda: self.make_peer().create_answer(code), 'answer')

    def accept(self):
        if self.peer is None or not self.host:
            return
        code = self.input.get('1.0', 'end').strip()
        self.job(lambda: self.peer.accept_answer(code), 'accepted')

    def copy(self):
        text = self.output.get('1.0', 'end').strip()
        if text:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)

    def start_game(self):
        if self.game:
            self.game.start_game()
            self.status.configure(text='Preparando ambos juegos por la conexión P2P...')
            self.refresh()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.jobs.get_nowait()
                self.busy = False
                if kind in ('offer', 'answer'):
                    self.output.configure(state='normal')
                    self.output.delete('1.0', 'end')
                    self.output.insert('1.0', value)
                    self.output.configure(state='disabled')
                    self.last_ui_error = ''
                    self.status.configure(text='Envía este código a tu amigo. Solo él debe pulsar Responder invitación. Tienes 30 minutos.' if kind == 'offer' else 'Devuelve este código al anfitrión. Él debe pulsar Aplicar respuesta. Puedes esperar hasta 30 minutos.')
                    if not self.game:
                        self.game = P2PGame(self.owner, self.peer, self.host, self.listening)
                    self.describe_candidates()
                elif kind == 'accepted':
                    self.last_ui_error = ''
                    self.status.configure(text='Comprobando rutas entre ambas PC...')
                elif kind == 'error':
                    self.last_ui_error = value['message']
                    self.status.configure(text=value['message'])
                    # An invalid paste can be corrected without regenerating an
                    # already valid host offer. A failed new offer/answer resets.
                    if self.peer and value['source'] != 'accepted':
                        self.peer.close()
                        self.peer = None
        except queue.Empty:
            pass
        if self.peer:
            try:
                while True:
                    kind, value = self.peer.events.get_nowait()
                    if kind == 'connected':
                        self.status.configure(text='Conexión P2P cifrada lista. El anfitrión puede pulsar START.')
                        if not self.game:
                            self.game = P2PGame(self.owner, self.peer, self.host, self.listening)
                        self.describe_candidates()
                    elif kind == 'message' and self.game:
                        self.game.message(value)
                    elif kind == 'error':
                        self.status.configure(text=value)
                        self.owner.return_room_process()
                    elif kind == 'game_closed':
                        self.owner.return_room_process()
            except queue.Empty:
                pass
        if self.game:
            self.game.poll()
            try:
                while True:
                    kind, value = self.game.events.get_nowait()
                    self.status.configure(text='Ambos juegos están conectados por P2P.' if kind == 'playing' else value)
            except queue.Empty:
                pass
        self.refresh()
        self.timer = self.window.after(100, self.poll)

    def describe_candidates(self):
        if not self.peer:
            return
        info = self.peer.snapshot()
        candidates = info.get('candidates', {})
        if not candidates.get('srflx') and not candidates.get('relay'):
            self.detail.configure(text='No se obtuvo dirección pública por STUN. Se probarán rutas locales/IPv6; guarda el diagnóstico si no conecta.')
        else:
            self.detail.configure(text='STUN encontró una dirección pública. ICE comprobará si la ruta directa funciona.')

    def export(self):
        if self.peer:
            target = self.data_path / 'diagnostics' / ('ice_' + str(time.time_ns()) + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(dict(self.peer.snapshot(), last_ui_error=self.last_ui_error), indent=2, ensure_ascii=False), encoding='utf-8')
            self.status.configure(text=loc.tr('Diagnóstico guardado: ') + str(target))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.game:
            self.game.close()
        if self.peer:
            self.peer.close()
        with self.owner.launch_lock:
            self.owner.close_process(self.owner.process)
            self.owner.process = None
        self.window.after_cancel(self.timer)
        self.window.destroy()
        self.owner.p2p_window = None
        self.owner.update_join_button()
        self.owner.local_button.configure(state='disabled' if self.owner.room else 'normal')
        self.owner.create_button.configure(state='disabled' if self.owner.room else 'normal')
