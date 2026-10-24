"""English / Spanish UI strings. Player names, room descriptions and chat stay untouched."""
import re
from tkinter import ttk
from privacy import public_text

language = "en"
WORDS = {
    'Ping entre PC: se medirá al conectar la partida.': 'Peer ping: measured when the game connects.',
    'Ping entre PC: no disponible en esta conexión.': 'Peer ping: unavailable on this connection.',
    'Ping entre PC: esperando conexión.': 'Peer ping: waiting for a connection.',
    'Ping entre PC: midiendo...': 'Peer ping: measuring...',
    'Ping entre PC: sin muestra reciente.': 'Peer ping: no recent sample.',
    'Modo LAN: solo salas de esta red. El directorio de Internet todavía no está configurado.': 'LAN mode: rooms on this network only. The Internet directory is not configured yet.',
    'Conectando PC': 'Connecting PCs',
    'Conectando las PC automáticamente... No necesitas copiar códigos.': 'Connecting the PCs automatically... No codes to copy.',
    'Conexión automática entre las PC. El directorio no transmite la partida.': 'Automatic connection between PCs. The directory does not carry gameplay.',
    'Conectar por código P2P': 'Connect by P2P code',
    'Conexión P2P': 'P2P connection',
    'TM3 Online | Conexión P2P': 'TM3 Online | P2P connection',
    'P2P · Conectar dos PC': 'P2P · Connect two PCs',
    'Sal de la sala y cierra el juego antes de abrir P2P.': 'Leave your room and close the game before opening P2P.',
    '1. El anfitrión crea y envía su invitación.\n2. El invitado la pega, genera una respuesta y la devuelve.\n3. El anfitrión aplica la respuesta. Cuando conecte, pulsa START.': '1. The host creates and sends an invitation.\n2. The guest pastes it, generates an answer and sends it back.\n3. The host applies the answer. Once connected, select START.',
    'Crear invitación': 'Create invitation', 'Responder invitación': 'Answer invitation',
    'Aplicar respuesta': 'Apply answer', 'Copiar mi código': 'Copy my code',
    'Pega aquí el código que recibiste:': 'Paste the code you received here:',
    'Tu código para enviar al otro equipo:': 'Your code to send to the other PC:',
    'Listo para crear o responder una invitación.': 'Ready to create or answer an invitation.',
    'Las invitaciones vencen en 10 minutos. Compártelas solo con tu amigo.': 'Invitations expire in 10 minutes. Share them only with your friend.',
    'Volver al menú': 'Return to menu', 'Guardar diagnóstico': 'Save diagnostics',
    'Cerrar conexión': 'Close connection', 'Buscando rutas ICE y dirección pública...': 'Finding ICE routes and a public address...',
    'Preparando ambos juegos por la conexión P2P...': 'Preparing both games over the P2P connection...',
    'Envía este código a tu amigo y espera su respuesta.': 'Send this code to your friend and wait for their answer.',
    'Devuelve tu código al anfitrión para que lo aplique en menos de un minuto.': 'Send your answer code back to the host to apply within one minute.',
    'Comprobando rutas entre ambas PC...': 'Checking routes between both PCs...',
    'Conexión P2P cifrada lista. El anfitrión puede pulsar START.': 'Encrypted P2P connection ready. The host can select START.',
    'Ambos juegos están conectados por P2P.': 'Both games are connected over P2P.',
    'No se obtuvo dirección pública por STUN. Se probarán rutas locales/IPv6; guarda el diagnóstico si no conecta.': 'STUN did not return a public address. Local/IPv6 routes will be tried; save diagnostics if it fails.',
    'STUN encontró una dirección pública. ICE comprobará si la ruta directa funciona.': 'STUN found a public address. ICE will check whether a direct route works.',
    'Diagnóstico guardado: ': 'Diagnostics saved: ',
    'Archivos listos. Esperando al anfitrión...': 'Files ready. Waiting for the host...',
    'Comprobando el otro equipo...': 'Checking the other PC...',
    'Ambos pueden volver a iniciar. La conexión P2P sigue abierta.': 'You can start again. The P2P connection remains open.',
    "Conexión a Internet": "Internet connection",
    "Dirección HTTPS del lobby público. Vacío para red local:": "Public lobby HTTPS address. Leave empty for local network:",
    "Usa una dirección HTTPS válida para el lobby público.": "Enter a valid HTTPS address for the public lobby.",
    "Conexión guardada. Vuelve a abrir el lobby para aplicarla.": "Connection saved. Reopen the lobby to apply it.",
    "Conexión por relay de Internet. No necesitas abrir puertos del router.": "Connected through the Internet relay. No router port forwarding needed.",
    "Dos PC por sala. Para probar 2+2, activa el segundo jugador en los mandos de cada PC.": "Two PCs per room. To test 2+2, enable player 2 in each PC's controller settings.",
    "Invitado": "Guest", "Esperando jugador...": "Waiting for a player...",
    "TM3 Online | Salas": "TM3 Online | Lobby", "Crear sala": "Create room", "Unirse": "Join room",
    "Jugar local": "Play locally", "Reconectar": "Reconnect", "Bienvenido a TM3 Online": "Welcome to TM3 Online",
    "Buscando conexión...": "Finding a connection...", "Buscando salas automáticamente...": "Looking for rooms...",
    "Crea tu sala o elige una para unirte. Máximo: 2 jugadores por sala.": "Create a room or join a friend. Two players per room.",
    "Descripción de sala": "Room", "Anfitrión": "Host", "Jugadores": "Players", "Estado": "Status",
    "Todavía no estás en una sala.": "You haven't joined a room yet.", "Conectando al lobby...": "Connecting to the lobby...",
    "Buscando el directorio y las salas...": "Finding the directory and rooms...", "Salir de la sala": "Leave room",
    "Cerrar sala": "Close room", "Saliendo de la sala...": "Leaving the room...", "Chat de la sala": "Room chat",
    "Enviar": "Send", "El lobby general sigue abierto para consultar todas las salas.": "The lobby stays open so you can browse other rooms.",
    "Conectado": "Connected", "Conectado al lobby de la red local": "Connected to your local network",
    "No se pudo conectar al lobby. Pulsa Reconectar para volver a buscar.": "Couldn't connect. Select Reconnect to try again.",
    "Sin conexión": "Offline", "Elegir otro usuario": "Choose another player name", "En espera": "Waiting",
    "Preparando": "Preparing", "Abriendo anfitrion": "Starting host", "Abriendo invitado": "Starting guest",
    "Partida iniciada": "Game started", "Llena": "Full", "Espera al otro jugador.": "Waiting for another player.",
    "El anfitrion puede pulsar START.": "The host can select START.",
    "No hay salas creadas. Pulsa Crear sala para ser anfitrión.": "No rooms yet. Create one and invite a friend.",
    "Selecciona una sala disponible y pulsa Unirse. La lista se actualiza automáticamente.": "Select an available room and join. The list updates automatically.",
    "Juego local abierto. No necesita otra computadora ni una sala.": "Local game opened. No room or second computer needed.",
    "Tu usuario": "Player name", "Usuario": "Player", "Descripción de sala": "Room description",
    "Crea tu nombre de jugador (2 a 24 caracteres):": "Choose your player name (2–24 characters):",
    "Descripción de la sala (1 a 100 caracteres):": "Describe your room (1–100 characters):",
    "Juego local": "Local game", "Disponible": "Available", "Puesto": "Seat", "Jugador": "Player", "Rol": "Role",
    "El mensaje puede tener hasta 500 caracteres.": "Messages can contain up to 500 characters.",
    "Tu juego sigue abierto. Cierralo antes de iniciar otra partida.": "Your emulator is still open. Close it before starting another session.",
    "Sal de la sala o espera a que termine la solicitud antes de jugar local.": "Leave your room or wait for the request to finish before playing locally.",
    "JUEGO LOCAL": "LOCAL PLAY", "SALAS EN LÍNEA": "ONLINE ROOMS", "Tu próxima partida empieza aquí.": "Your next match starts here.",
    "Juega en esta computadora. Sin sala ni conexión.": "Play on this computer. No room or connection required.",
    "Eres el anfitrión · Tú inicias la partida": "You are the host · You start the game",
    "Eres el invitado · El anfitrión inicia la partida": "You are the guest · The host starts the game",
    "Comprobando los archivos de ambos jugadores...": "Checking both players' game files...",
    "Abriendo el juego del anfitrión...": "Opening the host's game...",
    "Abriendo el juego del invitado...": "Opening the guest's game...",
    "Se inició la apertura de ambos juegos.": "Both games have been launched.",
    "Espera a que se una otro jugador.": "Waiting for another player to join.",
    "Los dos jugadores están en la sala. Pulsa START para abrir ambos juegos.": "Both players are here. Select START to launch both games.",
    "Ya estás en la sala. Espera a que el anfitrión pulse START.": "You have joined. Wait for the host to select START.",
}

def tr(text):
    if isinstance(text, str):
        text = public_text(text)
    if language == "es" or not isinstance(text, str):
        return text
    if text in WORDS:
        return WORDS[text]
    patterns = [(r"Ping entre PC \(RTT\): ([\d.]+) ms · Promedio: ([\d.]+) ms · Variación: ([\d.]+) ms",
                 r"Peer ping (RTT): \1 ms · Average: \2 ms · Variation: \3 ms"),
                (r"Bienvenido, (.*)", r"Welcome, \1"),
                (r"(.*)\nAnfitrión: (.*)  ·  (.*) jugadores", r"\1\nHost: \2  ·  \3 players"),
                (r"Estás en la sala de (.*)\. Su ventana está abierta\.", r"You are in \1's room. Its window is open."),
                (r"Detalle del error: (.*)", r"Error details: \1"),
                (r"Sala de (.*)", r"\1's room")]
    for pattern, replacement in patterns:
        if re.fullmatch(pattern, text):
            return re.sub(pattern, replacement, text)
    return text

class Localized:
    def __init__(self, master=None, **kwargs):
        self.source_text = kwargs.get("text", "")
        if "text" in kwargs:
            kwargs["text"] = tr(kwargs["text"])
        super().__init__(master, **kwargs)

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self.source_text = kwargs["text"]
            kwargs["text"] = tr(kwargs["text"])
        return super().configure(cnf, **kwargs)

    def retranslate(self):
        super().configure(text=tr(self.source_text))

class Label(Localized, ttk.Label):
    pass

class Button(Localized, ttk.Button):
    pass
