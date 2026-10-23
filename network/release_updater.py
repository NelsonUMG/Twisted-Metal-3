"""GitHub Releases installer updates. No credentials are stored on clients."""
import hashlib
import json
import os
from urllib.error import HTTPError
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPOSITORY = 'NelsonUMG/Twisted-Metal-3'
ASSET = 'TM3Online-Setup.exe'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'

def version_tuple(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Versión de publicación inválida')
    return tuple(map(int, value.lstrip('v').split('.')))

def check_update(current):
    request = Request(API, headers={'User-Agent': 'TM3Online-Updater', 'Accept': 'application/vnd.github+json'})
    try:
        with urlopen(request, timeout=15) as response:
            release = json.loads(response.read(1024 * 1024))
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
    digest = hashlib.sha256(); size = 0
    try:
        with urlopen(Request(update['url'], headers={'User-Agent': 'TM3Online-Updater'}), timeout=30) as response, temporary.open('wb') as target:
            if urlsplit(response.geturl()).scheme != 'https':
                raise ValueError('Redirección insegura')
            if progress: progress(0, update['size'])
            while block := response.read(256 * 1024):
                if cancelled and cancelled.is_set(): raise InterruptedError('Descarga cancelada')
                size += len(block)
                if size > update['size']:
                    raise ValueError('El instalador supera el tamaño declarado')
                digest.update(block); target.write(block)
                if progress: progress(size, update['size'])
        if size != update['size'] or digest.hexdigest() != update['sha256']:
            raise ValueError('El instalador descargado no coincide con SHA256')
        if cancelled and cancelled.is_set(): raise InterruptedError('Descarga cancelada')
        temporary.replace(path)
        return path
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
