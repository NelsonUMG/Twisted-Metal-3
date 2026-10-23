# TM3 room directory — Workers + SQLite Durable Objects

This is a control API for the desktop lobby, not a game server or a website.
One named Durable Object coordinates all rooms; the game stays on the PCs.
WebSocket RPC uses the Hibernation API. No Python or game files are deployed.

## Current status

Published on 2026-10-22 after the owner created their account and personally
approved Wrangler OAuth. Public HTTPS/WSS room discovery and automatic signaling
were verified with the frozen lobby at:

`https://tm3-room-directory.tm3-room-directory.workers.dev`

No domain or paid plan was purchased. SQLite-backed Durable Objects are
supported on Workers Free, subject to its quotas. Do not subscribe to Workers
Paid for this prototype. This deployment is a directory, NOT a gameplay relay;
gameplay between two real ISPs/mobile Internet still needs validation.

## Local developer checks (no account)

Node.js 22+ is required on the administrator's machine only:

```powershell
npm ci
npm test
npm run dev
```

`lab.mjs` is a completely local, ephemeral Miniflare service used by the Python
end-to-end QA harness. It listens on 127.0.0.1 and prints its selected port.
Sending any line on stdin disposes the runtime. Never publish its local URL.

## Public deployment — owner must authorize

1. The owner creates/signs into their own free Cloudflare account.
2. From this project folder, run `npx wrangler login --scopes account:read user:read workers_scripts:write`. The owner completes the
   browser authorization personally; no password/token belongs in the chat.
3. Run `npm ci` and `npm run deploy`. The checked-in `wrangler.jsonc` defines a
   Worker, one SQLite Durable Object class and its initial migration.
4. Copy the real HTTPS `workers.dev` address printed by deployment. Verify GET
   `/` returns `service: TM3Lobby`, `version: 3`, `websocket_rpc: 1`.
5. In the development workspace, run `tools/verify_public_rooms.py --url URL`
   with the lobby Python environment. It verifies the installed frozen client's
   public HTTPS/WSS, room discovery, privacy, and automatic signaling. The game
   peers in this check run on one PC: it is NOT a cross-ISP gameplay test.
6. Put the verified URL in `network/directory_defaults.py` and rebuild using
   `tools/update_ui2_session_release.py --refresh`. The builder requires matching
   verification evidence in `diagnostics/rooms_auto_v1/public_installed.json`.
   This bakes a default into every new lobby without overwriting personal
   configuration. Explicit empty `directory_url` continues to mean LAN.
7. Test home Internet against a mobile hotspot on the other PC. Save both lobby
   diagnostics if ICE cannot establish a direct route; a relay may be necessary.

Creating the account and authorizing publication are owner actions. The shipped
project has no account ID, API key, password, fictitious URL or billing setup.
The CLI's login credentials stay in the owner's local Wrangler configuration.
Do not ship `.wrangler`, `.dev.vars`, `.env`, node_modules or auth credentials.

## Protocol and boundaries

GET `/` is the health/capability endpoint. GET `/ws` upgrades to WebSocket.
Requests are `{id: integer, data: {op, token?, ...}}`; responses preserve id and
contain `result` or a bounded `error`. A token is bound to its own WebSocket,
not a transferable claim to someone else's seat. Player identities are temporary.

The authoritative lifecycle is:

`waiting → connect → prepare → host → client → playing → waiting`.

Host-only START increments generation. Only the host publishes `ice_offer`;
only the guest publishes `ice_answer`. Signals are private to the two members.
Both must report an encrypted channel ready before preparing either emulator.
The desktop runs the existing native protocol 7 with roles host=2 / guest=1.
Stale generations, wrong roles, replacement signals and full-room joins fail.

Room list summaries carry no chat, addresses or ICE credentials. Members receive
their own room's bounded chat and only the remote signal they need. Signaling
state is cleared after negotiation. No camera/microphone/media tracks are used.

Metadata is persisted as a bounded JSON row per room in SQLite. Only changed
rows are written; polling/heartbeat uses WebSocket attachments, which survive
hibernation. Rows are deleted on room closure or expiry. Cloudflare is trusted
for signaling; this is not a claim of zero provider data retention. Optional
observability is disabled, and the code does not log request bodies or tokens.

Presence timeout is 90 seconds plus an alarm sweep up to 60 seconds. Connection
setup is bounded to 90 seconds; emulator preparation stages to 30 seconds.
Client heartbeat/poll is about once per second, with no HTTP request per poll.

Caps: 64 rooms, 256 sockets, 8 sockets per source network, 8 RPCs/sec/socket,
36,000 characters/request, 32,000-character opaque ICE signal, 100 chat messages
per room and 500 Unicode code points/message. These are safety caps, NOT a
promise that continuous maximum load is free. Monitor Workers/DO request,
duration, SQL/storage quotas and abuse. Anonymous attackers could still exhaust
a free quota; stronger admission/WAF controls may be needed for broad release.

No TURN service is provisioned. Workers only solves discovery and signaling;
some restrictive CGNAT/UDP-blocking networks still require a relay for gameplay.

Primary docs: [WebSockets](https://developers.cloudflare.com/durable-objects/best-practices/websockets/),
[pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/),
[limits](https://developers.cloudflare.com/workers/platform/limits/).
