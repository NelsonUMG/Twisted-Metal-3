"""Room startup over the reliable peer channel, using the existing lobby owner."""
import queue
import socket
import threading
import time


class P2PGame:
    def __init__(self, owner, peer, host, listening):
        self.owner, self.peer, self.host, self.listening = owner, peer, host, listening
        self.generation = 0
        self.state = 'waiting'
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.jobs = queue.Queue(maxsize=8)
        self.events = queue.Queue()
        self.guest_prepared = False
        self.thread = threading.Thread(target=self.run, name='TM3P2PGame', daemon=True)
        self.thread.start()

    def send(self, op):
        self.peer.send_message(dict(op=op, generation=self.generation))

    def start_game(self):
        if not self.host or self.state != 'waiting' or not self.peer.connected.is_set():
            return
        self.state = 'starting'
        self.generation += 1
        self.ready.clear()
        self.jobs.put_nowait(self.start_host)

    def message(self, value):
        generation = value.get('generation')
        op = value.get('op')
        if type(generation) is not int or not 1 <= generation <= 2147483647:
            return
        if op == 'prepare' and not self.host:
            if generation != self.generation + 1 or self.state != 'waiting':
                return
            self.generation, self.state = generation, 'starting'
            self.guest_prepared = False
            self.jobs.put_nowait(self.prepare_guest)
        elif generation == self.generation:
            if op == 'ready' and self.host:
                self.ready.set()
            elif op == 'host_ready' and not self.host and self.state == 'starting':
                # Queue behind prepare_guest; never race its ready notification.
                self.jobs.put_nowait(self.start_guest)
            elif op == 'abort':
                self.owner.return_room_process()
                self.state = 'waiting'
                self.events.put(('error', 'El otro equipo no pudo iniciar la partida.'))

    def run(self):
        while not self.stop.is_set():
            try:
                job = self.jobs.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                job()
            except Exception as exc:
                self.owner.return_room_process()
                try:
                    if not self.stop.is_set():
                        self.send('abort')
                except Exception:
                    pass
                self.state = 'waiting'
                self.events.put(('error', str(exc)))

    def wait_for(self, predicate, seconds, message):
        end = time.monotonic() + seconds
        while True:
            if self.stop.is_set() or not self.peer.connected.is_set():
                raise ValueError('La conexión P2P se cerró.')
            if predicate():
                return
            if time.monotonic() > end:
                raise ValueError(message)
            self.stop.wait(.05)

    def prepare(self):
        process = self.owner.process
        if process and process.poll() is None:
            if self.owner.session_state().get('state') not in ('returned', 'closed', 'failed'):
                raise ValueError('Vuelve al menú o cierra el juego antes de iniciar otra partida.')
            self.owner.close_process(process)
            self.owner.process = None
        self.peer.detach_game()
        self.owner.runtime()

    def prepare_guest(self):
        self.prepare()
        self.guest_prepared = True
        self.send('ready')
        self.events.put(('status', 'Archivos listos. Esperando al anfitrión...'))

    def start_host(self):
        self.prepare()
        self.send('prepare')
        self.events.put(('status', 'Comprobando el otro equipo...'))
        self.wait_for(self.ready.is_set, 20, 'El otro equipo no confirmó sus archivos.')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        self.owner.process = self.owner.launch_game('lobby_host', ['--host', str(port)])
        self.wait_for(lambda: self.listening(self.owner.process.pid, port), 8, 'El juego anfitrión no abrió su puerto local.')
        self.peer.attach_game(port, generation=self.generation)
        self.send('host_ready')
        self.wait_connected()

    def start_guest(self):
        if not self.guest_prepared:
            raise ValueError('El invitado aún no está preparado.')
        self.guest_prepared = False  # Ignore duplicate host_ready commands.
        self.wait_for(lambda: True, 1, '')
        port = self.peer.attach_game(generation=self.generation)
        self.wait_for(lambda: True, 1, '')
        self.owner.process = self.owner.launch_game('lobby_client', ['--join', f'127.0.0.1:{port}'])
        self.wait_connected()

    def wait_connected(self):
        def connected():
            if self.owner.process.poll() is not None or self.owner.session_state().get('state') == 'failed':
                raise ValueError('El emulador no pudo iniciar la conexión.')
            return self.owner.session_state().get('state') == 'connected'
        self.wait_for(connected, 25, 'No se confirmó el inicio del juego. Guarda el diagnóstico ICE.')
        self.state = 'playing'
        self.events.put(('playing', None))

    def poll(self):
        if self.state == 'playing':
            process = self.owner.process
            if (self.owner.session_state().get('state') in ('returned', 'closed', 'failed') or
                    process is None or process.poll() is not None):
                self.state = 'waiting'
                self.events.put(('status', 'Ambos pueden volver a iniciar. La conexión P2P sigue abierta.'))

    def close(self):
        self.stop.set()
        self.ready.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
