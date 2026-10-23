import {test} from 'node:test';
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import {Miniflare} from 'miniflare';

async function lab(t) {
  const mf = new Miniflare({modules: true,
    scriptPath: fileURLToPath(new URL('../src/worker.js', import.meta.url)),
    compatibilityDate: '2026-07-30',
    durableObjects: {LOBBY: {className: 'RoomDirectory', useSQLite: true}}});
  const peers = [];
  t.after(async () => {for (const p of peers) {try {p.socket.close();} catch {}} await mf.dispose();});
  const connect = async name => {
    const upgrade = await mf.dispatchFetch('http://localhost/ws', {headers: {Upgrade: 'websocket'}});
    assert.equal(upgrade.status, 101);
    const socket = upgrade.webSocket;
    socket.accept();
    let serial = 0;
    const p = {socket, token: null, async call(op, data = {}) {
      await delay(140); // Stay within the production per-socket abuse limit.
      const id = ++serial;
      const reply = new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('No reply')), 3000);
        socket.addEventListener('message', event => {clearTimeout(timer); resolve(JSON.parse(event.data));}, {once: true});
      });
      socket.send(JSON.stringify({id, data: {op, token: p.token, ...data}}));
      const result = await reply;
      assert.equal(result.id, id);
      if (result.error) throw new Error(result.error);
      return result.result;
    }};
    peers.push(p);
    p.token = (await p.call('login', {name, automatic_ice: 1})).token;
    return p;
  };
  return {mf, connect};
}

test('health endpoint and rejection of web origins / non-websocket access', async t => {
  const {mf} = await lab(t);
  assert.equal((await (await mf.dispatchFetch('http://localhost/')).json()).websocket_rpc, 1);
  assert.equal((await mf.dispatchFetch('http://localhost/ws')).status, 426);
  assert.equal((await mf.dispatchFetch('http://localhost/ws', {headers: {Upgrade: 'websocket', Origin: 'https://evil.example'}})).status, 403);
});

test('all clients see rooms, but only members see private room data', async t => {
  const {connect} = await lab(t);
  const a = await connect('Anfitrión'), b = await connect('Invitado'), c = await connect('Observador');
  const room = (await a.call('create', {description: 'Combate TM3'})).room;
  assert.equal((await b.call('poll')).rooms[0].id, room.id);
  await b.call('join', {room: room.id});
  await a.call('chat', {text: 'Privado'});
  assert.equal((await b.call('poll')).room.chat.at(-1).text, 'Privado');
  const outside = await c.call('poll');
  assert.deepEqual(outside.rooms[0].chat, []);
  assert.equal(outside.rooms[0].transport, null);
  await assert.rejects(() => c.call('chat', {text: 'Intruso'}));
  await assert.rejects(() => c.call('join', {room: room.id}));
});

test('automatic negotiation, readiness, host/client launch, cancel and new generation', async t => {
  const {connect} = await lab(t);
  const a = await connect('Host'), b = await connect('Guest'), c = await connect('Spy');
  const room = (await a.call('create', {description: 'Automatic test'})).room;
  await b.call('join', {room: room.id});
  await assert.rejects(() => b.call('start'));
  let state = (await a.call('start')).room;
  const generation = state.generation;
  assert.equal(state.phase, 'connect');
  await assert.rejects(() => b.call('ice_offer', {generation, code: 'TM3ICE1.offer'}));
  await a.call('ice_offer', {generation, code: 'TM3ICE1.offer'});
  assert.equal((await b.call('poll')).room.transport.offer, 'TM3ICE1.offer');
  assert.equal((await c.call('poll')).rooms[0].transport, null);
  await b.call('ice_answer', {generation, code: 'TM3ICE1.answer'});
  assert.equal((await a.call('poll')).room.transport.answer, 'TM3ICE1.answer');
  await a.call('ice_ready', {generation});
  assert.equal((await b.call('ice_ready', {generation})).room.phase, 'prepare');
  await a.call('ready', {generation});
  assert.equal((await b.call('ready', {generation})).room.phase, 'host');
  await assert.rejects(() => b.call('host_started', {generation}));
  assert.equal((await a.call('host_started', {generation})).room.phase, 'client');
  assert.equal((await b.call('client_started', {generation})).room.phase, 'playing');
  assert.equal((await b.call('cancel', {generation})).room.phase, 'waiting');
  state = (await a.call('start')).room;
  assert.equal(state.generation, generation + 1);
  await assert.rejects(() => a.call('ice_offer', {generation, code: 'TM3ICE1.stale'}));
});

test('identity is bound to its websocket and no participant can replace a published signal', async t => {
  const {connect} = await lab(t);
  const a = await connect('Host'), b = await connect('Guest');
  const room = (await a.call('create', {description: 'Identity'})).room;
  await assert.rejects(() => b.call('poll', {token: a.token}), /Sesion vencida/);
  await b.call('join', {room: room.id});
  const {generation} = (await a.call('start')).room;
  await a.call('ice_offer', {generation, code: 'TM3ICE1.first'});
  await assert.rejects(() => a.call('ice_offer', {generation, code: 'TM3ICE1.changed'}));
  await assert.rejects(() => a.call('ice_answer', {generation, code: 'TM3ICE1.wrong_role'}));
});

test('guest disconnect frees the seat; host logout removes the room', {timeout: 15000}, async t => {
  const {connect} = await lab(t);
  const a = await connect('Host'), b = await connect('Guest');
  const room = (await a.call('create', {description: 'Exit'})).room;
  await b.call('join', {room: room.id});
  b.socket.close(); await delay(500);
  const afterClose = await a.call('poll');
  assert.equal(afterClose.room.players.length, 1, JSON.stringify(afterClose.room));
  await a.call('logout');
  const c = await connect('Observer');
  assert.deepEqual((await c.call('poll')).rooms, []);
});

test('invalid text / message schema, duplicate names, signal size and errors stay bounded', async t => {
  const {connect, mf} = await lab(t);
  const a = await connect('Host');
  await assert.rejects(() => connect('host'), /conectado/);
  for (const description of ['', 'x'.repeat(101), 'bad\nline']) await assert.rejects(() => a.call('create', {description}));
  await a.call('create', {description: 'Validation'});
  await a.call('chat', {text: '🎮'.repeat(500)});
  await assert.rejects(() => a.call('chat', {text: '🎮'.repeat(501)}));
  assert.equal((await mf.dispatchFetch('http://localhost/missing')).status, 404);
});

test('binary/malformed/oversized frames are rejected without exposing internals', async t => {
  const {connect} = await lab(t);
  const p = await connect('Validation');
  for (const frame of ['not-json', new Uint8Array(12), 'x'.repeat(36001), JSON.stringify({id: 1, data: null})]) {
    await delay(150);
    const reply = new Promise(resolve => p.socket.addEventListener('message', event => resolve(JSON.parse(event.data)), {once: true}));
    p.socket.send(frame);
    const value = await reply;
    assert.equal(typeof value.error, 'string');
    assert.ok(value.error.length < 240);
  }
});
