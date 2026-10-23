// Local test runtime, no account, no network publication, no persistent state.
import {Miniflare} from 'miniflare';
import {fileURLToPath} from 'node:url';
const mf = new Miniflare({modules: true, host: '127.0.0.1', port: 0,
  scriptPath: fileURLToPath(new URL('./src/worker.js', import.meta.url)),
  compatibilityDate: '2026-07-30', durableObjects: {LOBBY: {className: 'RoomDirectory', useSQLite: true}}});
console.log(JSON.stringify({url: String(await mf.ready)}));
process.stdin.once('data', async () => {await mf.dispose(); process.exit(0);});
