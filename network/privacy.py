"""Redact connection details before displaying or exporting diagnostics.

Public service addresses must remain usable internally; this is not encryption.
Operator API credentials must never be bundled in the application.
"""
import re

_URL = re.compile(r'\b(?:https?|wss?)://[^\s<>\"\']+', re.I)
_HOST = re.compile(r'\b[\w.-]+\.(?:workers\.dev|pages\.dev)\b', re.I)
_CREDENTIAL = re.compile(
    r'(?i)\b(authorization|api[_ -]?key|api[_ -]?token|access[_ -]?token|'
    r'account[_ -]?id|password|secret|token)\b[\"\']?\s*[:=]\s*'
    r'(?:[\"\'][^\"\']*[\"\']|[^\s,;}]+)')
_BEARER = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]+', re.I)
_PRIVATE_KEYS = {'authorization', 'apikey', 'apitoken', 'accesstoken',
                 'accountid', 'password', 'secret', 'token', 'directoryurl',
                 'sdp', 'ticket', 'credential'}


def public_text(value):
    text = str(value)
    text = _BEARER.sub('[redacted]', text)
    text = _CREDENTIAL.sub('[redacted]', text)
    return _HOST.sub('[service]', _URL.sub('[service]', text))


def public_diagnostic(value):
    if isinstance(value, dict):
        return {key: ('[redacted]' if re.sub(r'[^a-z]', '', str(key).lower())
                     in _PRIVATE_KEYS else public_diagnostic(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_diagnostic(item) for item in value]
    return public_text(value) if isinstance(value, str) else value
