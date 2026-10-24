"""GitHub Releases installer updates. No credentials are stored on clients."""
import hashlib
import http.client
import json
import os
import socket
import time
from urllib.error import HTTPError, URLError
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPOSITORY = 'NelsonUMG/Twisted-Metal-3'
ASSET = 'TM3Online-Setup.exe'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOAD_ATTEMPTS = 4
DOWNLOAD_TIMEOUT = 30


def _retryable_network_error(exc):
    if isinstance(exc, HTTPError):
        return exc.code in (408, 425, 429, 500, 502, 503, 504)
    if isinstance(exc, URLError):
        reason = exc.reason
        return isinstance(reason, (TimeoutError, socket.timeout, ConnectionError, OSError))
    return isinstance(exc, (TimeoutError, socket.timeout, ConnectionError,
                            http.client.HTTPException, OSError))


def _wait_to_retry(attempt, cancelled):
    delay = min(2 ** (attempt - 1), 8)
    if cancelled:
        if cancelled.wait(delay):
            raise InterruptedError('Descarga cancelada')
    else:
        time.sleep(delay)


def _read_url(request, timeout, cancelled=None):
    last_error = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        if cancelled and cancelled.is_set():
            raise InterruptedError('Descarga cancelada')
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read(1024 * 1024)
        except Exception as exc:
            if not _retryable_network_error(exc):
                raise
            last_error = exc
            if attempt == DOWNLOAD_ATTEMPTS:
                break
            _wait_to_retry(attempt, cancelled)
    raise URLError(f'No se pudo conectar después de {DOWNLOAD_ATTEMPTS} intentos: {last_error}')

def version_tuple(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Versión de publicación inválida')
    return tuple(map(int, value.lstrip('v').split('.')))

def check_update(current):
    request = Request(API, headers={'User-Agent': 'TM3Online-Updater', 'Accept': 'application/vnd.github+json'})
    try:
        release = json.loads(_read_url(request, timeout=30))
    except HTTPError as exc:
        if exc.code == 404: return None
        raise
    if release.get('draft') or release.get('prerelease'):
        return None
    tag = release['tag_name']
    if version_tuple(tag) <= version_tuple(current):
        return None
    manifest = next((a for a in release['assets'] if a['name'] == 'TM3Online-update.json'), None)
    if manifest:
        def descriptor(asset):
            digest = asset.get('digest', '')
            if not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):
                raise ValueError('Falta SHA256 del archivo')
            url=asset['browser_download_url']; parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.netloc!='github.com' or not parsed.path.startswith(f'/{REPOSITORY}/releases/download/'):
                raise ValueError('Origen de actualización inválido')
            size=asset['size']
            if type(size) is not int or not 0<=size<=512*1024*1024: raise ValueError('Tamaño inválido')
            return dict(url=url,size=size,sha256=digest[7:])
        return dict(version=tag, mode='files', manifest=descriptor(manifest),
            assets={a['name']:descriptor(a) for a in release['assets'] if a['name'].startswith('tm3-')})
    asset = next((a for a in release['assets'] if a['name'] == ASSET), None)
    if not asset:
        raise ValueError('La publicación todavía no tiene instalador')
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('GitHub no proporcionó SHA256 del instalador')
    url = asset['browser_download_url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith(f'/{REPOSITORY}/releases/download/'):
        raise ValueError('Origen de actualización inválido')
    size = asset['size']
    if not isinstance(size, int) or not 0 < size <= 500 * 1024 * 1024:
        raise ValueError('Tamaño de actualización inválido')
    return dict(version=tag, url=url, sha256=digest[7:], size=size)

def download_installer(update, cache, progress=None, cancelled=None):
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    path = cache / ASSET
    temporary = cache / (ASSET + '.partial')
    if path.is_file():
        with path.open('rb') as stream:
            if path.stat().st_size == update['size'] and hashlib.file_digest(stream, 'sha256').hexdigest() == update['sha256']:
                if progress: progress(update['size'], update['size'])
                return path
    request = Request(update['url'], headers={'User-Agent': 'TM3Online-Updater'})
    last_error = None
    try:
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            if cancelled and cancelled.is_set():
                raise InterruptedError('Descarga cancelada')
            digest = hashlib.sha256(); size = 0
            try:
                with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                    if urlsplit(response.geturl()).scheme != 'https':
                        raise ValueError('Redirección insegura')
                    with temporary.open('wb') as target:
                        if progress: progress(0, update['size'])
                        while block := response.read(256 * 1024):
                            if cancelled and cancelled.is_set():
                                raise InterruptedError('Descarga cancelada')
                            size += len(block)
                            if size > update['size']:
                                raise ValueError('El instalador supera el tamaño declarado')
                            digest.update(block); target.write(block)
                            if progress: progress(size, update['size'])
                if size != update['size'] or digest.hexdigest() != update['sha256']:
                    raise ValueError('El archivo descargado no coincide con SHA256')
                if cancelled and cancelled.is_set():
                    raise InterruptedError('Descarga cancelada')
                temporary.replace(path)
                return path
            except (ValueError, InterruptedError):
                raise
            except Exception as exc:
                if not _retryable_network_error(exc):
                    raise
                last_error = exc
                temporary.unlink(missing_ok=True)
                if attempt == DOWNLOAD_ATTEMPTS:
                    break
                _wait_to_retry(attempt, cancelled)
        raise URLError(f'No se pudo descargar tras {DOWNLOAD_ATTEMPTS} intentos: {last_error}')
    finally:
        temporary.unlink(missing_ok=True)

def launch_installer(path, directory, update=None):
    path = Path(path)
    if update:
        with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != update['size'] or digest != update['sha256']:
            raise ValueError('El instalador cambió después de la descarga')
    # Inno Setup waits for running applications to close before replacing files.
    return subprocess.Popen([str(path), '/SP-', '/SILENT', '/NORESTART', '/TM3RESTART=1', f'/WAITPID={os.getpid()}', f'/DIR={Path(directory).resolve()}'], shell=False)
