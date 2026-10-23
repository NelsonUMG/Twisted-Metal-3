"""TM3 relay v1. TM3-specific, not TURN/ICE. Internet uses validated HTTPS."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import struct
import time
from urllib.parse import urlsplit

VERSION = 1
UPGRADE = "tm3relay/1"
FRAME = struct.Struct("!cH")
CONTROL = struct.Struct("<IHHIIQ")
MAGIC = 0x4F334D54
MAX_FRAME = 4096
MAX_DATAGRAM = 1252  # NetBridge's 52-byte header + 1200-byte fragment.


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            any(c.isspace() or ord(c) < 32 for c in url)):
        raise ValueError("URL del relay invalida.")
    if parsed.scheme != "https" and not loopback(parsed.hostname):
        raise ValueError("El relay de Internet requiere HTTPS.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not 0 < port < 65536:
        raise ValueError("Puerto del relay invalido.")
    if (parsed.path or "/tm3-relay") != "/tm3-relay":
        raise ValueError("La ruta del relay debe ser /tm3-relay.")
    return parsed.hostname, port, "/tm3-relay", parsed.scheme == "https"


def validate_secret(secret):
    if not isinstance(secret, str) or len(secret.encode()) < 32:
        raise ValueError("TM3_RELAY_SECRET debe contener al menos 32 bytes aleatorios.")
    return secret


def issue_ticket(secret, session, side, now=None):
    validate_secret(secret)
    payload = json.dumps(dict(v=VERSION, session=session, side=side,
                              expires=int(time.time() if now is None else now) + 90),
                         sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().encode()
    return (body + b"." + signature).decode()


def verify_ticket(secret, ticket, now=None):
    validate_secret(secret)
    try:
        if not isinstance(ticket, str) or len(ticket) > 1024:
            raise ValueError()
        body, signature = ticket.encode("ascii").split(b".")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
        current = time.time() if now is None else now
        session = claims["session"]
        if (claims["v"] != VERSION or type(claims["side"]) is not int or claims["side"] not in (0, 1) or
                type(claims["expires"]) is not int or not current < claims["expires"] <= current + 95 or
                not isinstance(session, str) or len(session) != 48 or
                any(c not in "0123456789abcdef" for c in session)):
            raise ValueError()
        return claims
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise ValueError("Credencial de relay invalida o vencida.") from exc


async def read_frame(reader, timeout=20):
    async with asyncio.timeout(timeout):
        kind, size = FRAME.unpack(await reader.readexactly(FRAME.size))
        if size > MAX_FRAME:
            raise ValueError("Frame de relay demasiado grande.")
        return kind, await reader.readexactly(size)


async def write_frame(writer, kind, payload=b""):
    if len(payload) > MAX_FRAME:
        raise ValueError("Frame de relay demasiado grande.")
    writer.write(FRAME.pack(kind, len(payload)) + payload)
    await asyncio.wait_for(writer.drain(), 5)


def validate_game_frame(kind, data):
    if kind == b"C":
        if len(data) != CONTROL.size or CONTROL.unpack(data)[:2] != (MAGIC, 7):
            raise ValueError("Control TM3 invalido.")
    elif kind == b"D":
        if not 52 <= len(data) <= MAX_DATAGRAM or data[:4] != b"TM3O":
            raise ValueError("Datagrama TM3 invalido.")
    else:
        raise ValueError("Tipo de frame invalido.")
