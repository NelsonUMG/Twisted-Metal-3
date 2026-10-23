"""Bounded, out-of-band WebRTC descriptions. Never put these codes in logs."""
import base64
import binascii
import ipaddress
import json
import re
import secrets
import time
import zlib

PREFIX = 'TM3ICE1.'
MAX_CODE = 32000
MAX_RAW = 24000


class CodeValidationError(ValueError):
    pass


def encode_description(sdp, kind, session, expires):
    payload = dict(app='TM3Online', v=1, type=kind, session=session, expires=expires, sdp=sdp)
    code = PREFIX + base64.urlsafe_b64encode(zlib.compress(json.dumps(payload, separators=(',', ':')).encode(), 6)).decode()
    decode_description(code, kind)
    return code


def decode_description(code, kind, session=None, now=None):
    try:
        if not isinstance(code, str) or len(code) > MAX_CODE:
            raise ValueError()
        code = ''.join(code.split())
        if not code.startswith(PREFIX):
            raise ValueError()
        packed = base64.b64decode(code[len(PREFIX):], altchars=b'-_', validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, MAX_RAW + 1)
        if len(raw) > MAX_RAW or not decoder.eof or decoder.unused_data:
            raise ValueError()
        value = json.loads(raw)
        # Peer wall clocks are not trusted clocks. Lifetime is enforced by the
        # owning session using monotonic time, not this wire-format timestamp.
        if (value['app'] != 'TM3Online' or value['v'] != 1 or
                not isinstance(value['session'], str) or not re.fullmatch('[0-9a-f]{32}', value['session']) or
                type(value['expires']) is not int or not 0 <= value['expires'] < 2**63):
            raise ValueError()
        if value['type'] != kind:
            raise CodeValidationError('Pegaste una invitación, no una respuesta. En la otra PC pulsa Responder invitación y devuelve su código.' if kind == 'answer' else 'Ese código es una respuesta. Solo el anfitrión crea la invitación; aquí pega esa invitación.')
        if session is not None and not secrets.compare_digest(session, value['session']):
            raise CodeValidationError('La respuesta pertenece a otra invitación. Usa la respuesta de esta sala, sin crear otra invitación.')
        sdp = value['sdp']
        if not isinstance(sdp, str) or len(sdp) > 20000 or '\x00' in sdp:
            raise ValueError()
        lines = sdp.splitlines()
        media = [line for line in lines if line.startswith('m=')]
        if len(media) != 1 or not media[0].startswith('m=application ') or 'UDP/DTLS/SCTP' not in media[0]:
            raise ValueError()
        if not any(line.startswith('a=fingerprint:sha-256 ') for line in lines):
            raise ValueError()
        candidates = [line for line in lines if line.startswith('a=candidate:')]
        if not candidates or len(candidates) > 64:
            raise ValueError()
        for candidate in candidates:
            fields = candidate.split()
            ipaddress.ip_address(fields[4])
            if fields[2].lower() != 'udp' or not 0 < int(fields[5]) < 65536:
                raise ValueError()
        return value
    except CodeValidationError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, zlib.error, binascii.Error) as exc:
        raise ValueError('Código ICE incompleto o inválido. Copia el código completo con Copiar mi código.') from exc
