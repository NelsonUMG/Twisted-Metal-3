// Shared control plane only. Never accept game packets, discs or save files.
import { DurableObject } from 'cloudflare:workers';

const MAX_ROOMS = 64, MAX_CLIENTS = 256, SESSION_TTL = 90_000;
const hex = (bytes = 24) => Array.from(crypto.getRandomValues(new Uint8Array(bytes)), v => v.toString(16).padStart(2, '0')).join('');
class RequestError extends Error {}
const fail = message => { throw new RequestError(message); };
const validText = (s, max) => typeof s === 'string' && s.trim().length > 0 && Array.from(s).length <= max && !/[\x00-\x1f]/.test(s);
const response = (status, data) => Response.json(data, {status, headers: {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
const health = {service: 'TM3Lobby', version: 3, automatic_ice: 1, websocket_rpc: 1, relay_protocol: 0};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/' && request.method === 'GET') return response(200, health);
    if (url.pathname !== '/ws' || request.method !== 'GET') return response(404, {error: 'No existe.'});
    if (request.headers.get('Upgrade')?.toLowerCase() !== 'websocket') return response(426, {error: 'WebSocket requerido.'});
    const origin = request.headers.get('Origin');
    // Native clients send no Origin; do not expose the API to arbitrary websites.
    if (origin && origin !== url.origin) return response(403, {error: 'Origen no permitido.'});
    return env.LOBBY.get(env.LOBBY.idFromName('tm3-global-v1')).fetch(request);
  }
};

export class RoomDirectory extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx = ctx;
    this.rooms = {};
    this.persisted = new Map();
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec('CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, payload TEXT NOT NULL)');
      for (const row of ctx.storage.sql.exec('SELECT id, payload FROM rooms')) {
        this.rooms[row.id] = JSON.parse(row.payload);
        this.persisted.set(row.id, row.payload);
      }
    });
  }

  async fetch(request) {
    const sockets = this.ctx.getWebSockets();
    if (sockets.length >= MAX_CLIENTS) return response(503, {error: 'Directorio lleno. Intenta más tarde.'});
    const ip = request.headers.get('CF-Connecting-IP') || 'local-test';
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip));
    if (this.ctx.getWebSockets().length >= MAX_CLIENTS) return response(503, {error: 'Directorio lleno.'});
    const tag = Array.from(new Uint8Array(hash).slice(0, 16), n => n.toString(16).padStart(2, '0')).join('');
    if (this.ctx.getWebSockets(tag).length >= 8) return response(429, {error: 'Demasiadas conexiones desde esta red.'});
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server, [tag]);
    server.serializeAttachment({connected: Date.now(), seen: Date.now(), rateTime: Date.now(), rateCount: 0});
    // One alarm for the entire directory; no recurring billing when idle.
    if (await this.ctx.storage.getAlarm() === null) await this.ctx.storage.setAlarm(Date.now() + 60_000);
    return new Response(null, {status: 101, webSocket: client});
  }

  sessions() {
    return this.ctx.getWebSockets().map(socket => ({socket, ...socket.deserializeAttachment()})).filter(s => s.token);
  }

  roomFor(token) { return Object.values(this.rooms).find(room => room.players.includes(token)); }

  message(room, name, text, kind = 'text') {
    room.chat.push({id: ++room.chat_seq, name, text, kind, time: Date.now() / 1000});
    if (room.chat.length > 100) room.chat.shift();
  }

  leave(token) {
    let changed = false;
    for (const room of Object.values(this.rooms)) {
      if (room.owner === token) { delete this.rooms[room.id]; changed = true; }
      else if (room.players.includes(token)) {
        room.players = room.players.filter(t => t !== token);
        room.phase = 'waiting'; room.signals = {}; room.ready = []; room.ice_ready = [];
        room.error = 'El otro jugador salió.';
        this.message(room, 'Sistema', 'El otro jugador salió.', 'system'); changed = true;
      }
    }
    return changed;
  }

  prune(now = Date.now()) {
    let changed = false;
    const active = new Set();
    for (const socket of this.ctx.getWebSockets()) {
      const s = socket.deserializeAttachment();
      if (now - s.seen > SESSION_TTL) {
        if (s.token) changed = this.leave(s.token) || changed;
        socket.serializeAttachment({...s, token: null});
        try { socket.close(1000, 'Sesión vencida'); } catch {}
      } else if (s.token) active.add(s.token);
    }
    for (const room of Object.values(this.rooms)) {
      for (const token of [...room.players]) if (!active.has(token)) changed = this.leave(token) || changed;
      if (!this.rooms[room.id]) continue;
      if (['connect', 'prepare', 'host', 'client'].includes(room.phase) &&
          now - room.since > (room.phase === 'connect' ? 90_000 : 30_000)) {
        room.phase = 'waiting'; room.error = 'Se agotó el tiempo de conexión. Vuelve a pulsar START.';
        room.signals = {}; changed = true;
      }
    }
    return changed;
  }

  publicRoom(room, token, names) {
    const name = t => names.get(t) || 'Jugador';
    const member = room.players.includes(token);
    let transport = null;
    if (member && room.phase !== 'waiting') {
      transport = {mode: 'ice', generation: room.generation};
      const kind = token === room.owner ? 'answer' : 'offer';
      if (room.signals[kind]) transport[kind] = room.signals[kind];
    }
    return {id: room.id, host: name(room.owner), description: room.description,
      players: room.players.map(name), phase: room.phase, owner: token === room.owner,
      capacity: 2, joinable: room.phase === 'waiting' && room.players.length < 2,
      address: null, chat: member ? room.chat : [], generation: room.generation,
      error: room.error, connection_mode: 'ice', transport};
  }

  operate(socket, data) {
    const session = socket.deserializeAttachment();
    const now = Date.now();
    session.seen = now;
    socket.serializeAttachment(session);
    if (data.op === 'login') {
      if (session.token) fail('Ya estás conectado.');
      if (data.automatic_ice !== 1) fail('Actualiza TM3Lobby para conectar automáticamente.');
      if (typeof data.name !== 'string') fail('Nombre inválido.');
      const name = data.name.normalize('NFKC').trim();
      if (!/^[\p{L}\p{N}_ -]{2,24}$/u.test(name)) fail('Usa de 2 a 24 letras, números, espacios, _ o -.');
      if (this.sessions().some(s => s.name.toLowerCase() === name.toLowerCase())) fail('Ese usuario ya esta conectado.');
      session.token = hex(32); session.name = name;
      socket.serializeAttachment(session);
      return {token: session.token};
    }
    const token = session.token;
    if (!token || typeof data.token !== 'string' || token !== data.token) fail('Sesion vencida. Vuelve a conectar.');
    const room = this.roomFor(token);
    const generation = () => {
      if (!room || !Number.isSafeInteger(data.generation) || data.generation !== room.generation) fail('Inicio de partida vencido.');
    };
    switch (data.op) {
      case 'create': {
        if (room) fail('Ya estás en una sala.');
        if (Object.keys(this.rooms).length >= MAX_ROOMS) fail('No hay espacio para más salas.');
        if (!validText(data.description, 100)) fail('La descripción debe tener de 1 a 100 caracteres.');
        const id = hex(12);
        this.rooms[id] = {id, owner: token, description: data.description.trim(), players: [token],
          phase: 'waiting', generation: 0, ready: [], ice_ready: [], signals: {}, error: '', since: now, chat: [], chat_seq: 0};
        this.message(this.rooms[id], 'Sistema', `${session.name} creó la sala.`, 'system'); break;
      }
      case 'join': {
        const target = this.rooms[data.room];
        if (room || !target || target.phase !== 'waiting' || target.players.length !== 1) fail('La sala ya no está disponible.');
        target.players.push(token); target.error = '';
        this.message(target, 'Sistema', `${session.name} entró a la sala.`, 'system'); break;
      }
      case 'leave': this.leave(token); break;
      case 'logout':
        this.leave(token); socket.serializeAttachment({...session, token: null}); return {};
      case 'chat':
        if (!room) fail('Entra a una sala para chatear.');
        if (!validText(data.text, 500)) fail('El mensaje debe tener de 1 a 500 caracteres.');
        this.message(room, session.name, data.text.trim()); break;
      case 'start':
        if (!room || token !== room.owner || room.players.length !== 2 || room.phase !== 'waiting') fail('START requiere al anfitrión y dos jugadores.');
        room.generation++; room.phase = 'connect'; room.since = now;
        room.signals = {}; room.ready = []; room.ice_ready = []; room.error = ''; break;
      case 'ice_offer': case 'ice_answer': {
        generation();
        if (room.phase !== 'connect') fail('Negociación de sala vencida.');
        const kind = data.op === 'ice_offer' ? 'offer' : 'answer';
        if ((kind === 'offer') !== (token === room.owner) || (kind === 'answer' && !room.signals.offer)) fail('Negociación no autorizada.');
        if (typeof data.code !== 'string' || data.code.length > 32000 || !/^TM3ICE1\.[A-Za-z0-9_=-]+$/.test(data.code)) fail('Señal de conexión inválida.');
        if (room.signals[kind] && room.signals[kind] !== data.code) fail('La señal ya fue publicada.');
        room.signals[kind] = data.code; break;
      }
      case 'ice_ready':
        generation();
        if (room.phase !== 'connect' || !room.signals.answer) fail('Negociación de sala vencida.');
        if (!room.ice_ready.includes(token)) room.ice_ready.push(token);
        if (room.ice_ready.length === 2) { room.phase = 'prepare'; room.signals = {}; room.since = now; }
        break;
      case 'ready':
        generation();
        if (room.phase !== 'prepare') fail('Preparación vencida.');
        if (!room.ready.includes(token)) room.ready.push(token);
        if (room.ready.length === 2) { room.phase = 'host'; room.since = now; }
        break;
      case 'host_started':
        generation();
        if (token !== room.owner || room.phase !== 'host') fail('Inicio no autorizado.');
        room.phase = 'client'; room.since = now; break;
      case 'client_started':
        generation();
        if (token === room.owner || room.phase !== 'client') fail('Inicio no autorizado.');
        room.phase = 'playing'; break;
      case 'failed':
        generation();
        if (!['connect','prepare','host','client'].includes(room.phase)) fail('El intento de inicio ya terminó.');
        room.phase = 'waiting'; room.signals = {}; room.error = String(data.error || 'No se pudo iniciar.').slice(0, 240); break;
      case 'cancel':
        generation(); room.phase = 'waiting'; room.signals = {}; room.ready = []; room.error = ''; break;
      case 'poll': break;
      default: fail('Operación desconocida.');
    }
    const current = this.roomFor(token);
    const names = new Map(this.sessions().map(p => [p.token, p.name]));
    return {rooms: Object.values(this.rooms).map(r => ({...this.publicRoom(r, token, names), chat: [], transport: null, address: null})),
            room: current ? this.publicRoom(current, token, names) : null};
  }

  async webSocketMessage(socket, message) {
    let id = null;
    try {
      const rate = socket.deserializeAttachment();
      if (Date.now() - rate.rateTime >= 1000) {rate.rateTime = Date.now(); rate.rateCount = 0;}
      if (++rate.rateCount > 8) {socket.close(1008, 'Demasiadas solicitudes'); return;}
      socket.serializeAttachment(rate);
      if (typeof message !== 'string' || message.length > 36000) fail('Solicitud inválida.');
      const envelope = JSON.parse(message);
      id = envelope.id;
      if (!Number.isSafeInteger(id) || id < 1 || !envelope.data || typeof envelope.data !== 'object' || Array.isArray(envelope.data)) fail('Solicitud inválida.');
      const changed = this.prune();
      const result = this.operate(socket, envelope.data);
      // Only membership/chat/negotiation changes write storage. Heartbeats and
      // polling use WebSocket attachments and do not consume storage writes.
      if (changed || !['login','poll'].includes(envelope.data.op)) await this.persist();
      socket.send(JSON.stringify({id, result}));
    } catch (error) {
      socket.send(JSON.stringify({id, error: error instanceof SyntaxError ? 'JSON inválido.' : error instanceof RequestError ? error.message : 'El directorio no pudo completar la operación. Intenta más tarde.'}));
    }
  }

  async persist() {
    // One bounded JSON row per room; never a giant KV value containing all
    // rooms. Poll/heartbeat doesn't write; only actually changed rows do.
    const next = new Map();
    this.ctx.storage.transactionSync(() => {
      for (const room of Object.values(this.rooms)) {
        const payload = JSON.stringify(room);
        if (this.persisted.get(room.id) !== payload) {
          this.ctx.storage.sql.exec('INSERT INTO rooms (id, payload) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', room.id, payload);
        }
        next.set(room.id, payload);
      }
      for (const id of this.persisted.keys()) {
        if (!this.rooms[id]) {
          this.ctx.storage.sql.exec('DELETE FROM rooms WHERE id=?', id);
        }
      }
    });
    this.persisted = next;
  }

  async webSocketClose(socket, code, reason, wasClean) {
    const session = socket.deserializeAttachment();
    if (session?.token) {
      socket.serializeAttachment({...session, token: null});
      if (this.leave(session.token)) await this.persist();
    }
    try { socket.close(1000, 'Cerrado'); } catch {}
  }

  async webSocketError(socket) { await this.webSocketClose(socket); }

  async alarm() {
    if (this.prune()) await this.persist();
    if (this.ctx.getWebSockets().length) await this.ctx.storage.setAlarm(Date.now() + 60_000);
  }
}
