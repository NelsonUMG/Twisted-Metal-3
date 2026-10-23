"""Update the portable Vulkan ZIP with the low-delay local-audio runtime."""
from pathlib import Path
import copy
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT/'TM3Online_Portatil.zip'
BACKUP = ROOT/'TM3Online_Portatil_ANTES_AUDIO_SIN_PREBUFFER_20261022.zip'
PREFIX = 'TM3Online_UI2_175_20261021/'
SETTINGS = ROOT/'dist/TM3Online_UI2_175_20261021/runtime/TM3Console.ini'
ASSETS = ROOT/'diagnostics/vulkan_trial_20261022/assets'
SOURCE = ROOT/'diagnostics/vulkan_trial_20261022/source'
EXE = ROOT/'diagnostics/vulkan_trial_20261022/frozen/dist/TM3Lobby_Vulkan.exe'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build_core_source_archive(output):
    excluded_parts = {'.git', '__pycache__', 'build', 'Release', 'Debug'}
    excluded_suffixes = {'.a', '.bin', '.d', '.dll', '.exe', '.exp', '.lib',
                         '.obj', '.o', '.pdb', '.pyc', '.so'}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(SOURCE.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(SOURCE)
            if excluded_parts.intersection(relative.parts) or path.suffix.lower() in excluded_suffixes:
                continue
            archive.write(path, relative.as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert 'COPYING' in names and 'README.md' in names


def main():
    assert ZIP.is_file() and zipfile.is_zipfile(ZIP)
    assert SOURCE.is_dir() and (SOURCE/'COPYING').is_file()
    assert EXE.is_file() and EXE.stat().st_size > 5_000_000
    required_assets = ('beetle_psx_system256_vulkan.dll', 'tm3_vulkan_frontend.dll',
                       'libwinpthread-1.dll')
    for name in required_assets:
        assert (ASSETS/name).is_file(), name
    assert SETTINGS.is_file()
    desired_config = SETTINGS.read_text(encoding='utf-8-sig')
    assert 'Resolution=1' in desired_config and 'AudioLatency=' not in desired_config

    if not BACKUP.exists():
        shutil.copy2(ZIP, BACKUP)
    assert zipfile.is_zipfile(BACKUP)
    with zipfile.ZipFile(ZIP) as original:
        assert original.testzip() is None
        original_names = set(original.namelist())
        config = original.read(PREFIX+'runtime/TM3Console.ini').decode('utf-8-sig')
        assert 'Resolution=1' in config
        assert PREFIX+'runtime/system256/beetle_psx_system256.dll' in original_names
        assert PREFIX+'runtime/system256/beetle_psx_system256_vulkan.dll' in original_names

    docs = '''# SYSTEM256 — salas en línea con renderizado automático

1. Extrae la carpeta completa en ambas PC.
2. Abre TM3Lobby.exe en las dos y entra a la misma sala.
3. Cuando ICE esté conectado, el anfitrión pulsa START.
4. F11 alterna pantalla completa; Esc cierra la partida y vuelve al lobby.

La partida SYSTEM256 intenta usar Beetle PSX HW con Vulkan si ambas PC tienen
una GPU/controlador Vulkan compatible y el dispositivo se inicia correctamente.
Cada PC selecciona su propia GPU Vulkan discreta compatible; no necesita tener
el mismo modelo que la otra PC (por ejemplo, una GTX 1050 Ti y una RTX 4050).
Si una PC no puede iniciar Vulkan, ambas vuelven a Software antes de cargar la
partida. El paquete no instala ni sustituye el controlador de vídeo de Windows.

La resolución predeterminada es 1× (original), por fluidez. La imagen siempre
se presenta en 4:3, con bandas negras al maximizar o usar pantalla completa.
Se puede cambiar la resolución interna en Ajustes > Gráficos; es local y no
afecta la sincronización. Filtros y mejoras visuales pueden cambiar la
apariencia respecto a DuckStation; Vulkan por sí solo no aumenta la resolución.

El título de la ventana de juego muestra el renderizador activo. En Jugar local,
el emulador de escritorio tradicional sigue usando su ruta de Software; Vulkan
automático está habilitado en las partidas SYSTEM256 de las salas.

Cada PC genera y reproduce localmente el audio de su consola; el audio no
viaja por la red y comienza sin un prebúfer artificial de 80 ms. Se conserva
el búfer normal del dispositivo de audio. Cloudflare publica el directorio y
la señalización; ICE lleva los controles entre PC. No hay relay de juego
incluido: ciertas combinaciones de CGNAT todavía pueden impedir una partida.

El core Beetle PSX se distribuye bajo GPLv2. El código fuente correspondiente
y las licencias de terceros están en sources/ y licenses/.
'''

    with tempfile.TemporaryDirectory(prefix='tm3_vulkan_pack_') as temporary:
        temp = Path(temporary)
        source_archive = temp/'beetle_psx_system256_vulkan_source.zip'
        build_core_source_archive(source_archive)
        guide = temp/'SYSTEM256_PRUEBA_ES.md'
        guide.write_text(docs, encoding='utf-8')
        settings = temp/'TM3Console.ini'
        settings.write_text(desired_config, encoding='utf-8')
        replacements = {
            PREFIX+'TM3Lobby.exe': EXE,
            PREFIX+'SYSTEM256_PRUEBA_ES.md': guide,
            PREFIX+'runtime/TM3Console.ini': settings,
            PREFIX+'runtime/system256/beetle_psx_system256_vulkan.dll': ASSETS/'beetle_psx_system256_vulkan.dll',
            PREFIX+'runtime/system256/tm3_vulkan_frontend.dll': ASSETS/'tm3_vulkan_frontend.dll',
            PREFIX+'runtime/system256/libwinpthread-1.dll': ASSETS/'libwinpthread-1.dll',
            PREFIX+'licenses/COPYING_Beetle_GPLv2.txt': SOURCE/'COPYING',
            PREFIX+'licenses/LICENSE_libwinpthread.txt': ROOT/'TM3Online_Lobby/licenses/LICENSE_libwinpthread.txt',
            PREFIX+'sources/beetle_psx_system256_vulkan_source.zip': source_archive,
            PREFIX+'sources/system256_vulkan_frontend.cpp': ROOT/'network/system256_vulkan_frontend.cpp',
            PREFIX+'sources/system256/twin_core.py': ROOT/'256mb system/src/twin_core.py',
            PREFIX+'sources/system256/input_stream.py': ROOT/'256mb system/src/input_stream.py',
            PREFIX+'sources/system256/demand_feed.py': ROOT/'256mb system/src/demand_feed.py',
            PREFIX+'sources/network/system256_runtime.py': ROOT/'network/system256_runtime.py',
            PREFIX+'sources/network/system256_bridge.py': ROOT/'network/system256_bridge.py',
            PREFIX+'sources/network/lobby_client.py': ROOT/'network/lobby_client.py',
            PREFIX+'sources/network/lobby_entry.py': ROOT/'network/lobby_entry.py',
        }
        handle, temp_name = tempfile.mkstemp(prefix='TM3Online_Portatil_VULKAN_',
                                             suffix='.tmp.zip', dir=ROOT)
        os.close(handle)
        Path(temp_name).unlink()
        temporary_zip = Path(temp_name)
        try:
            written = set()
            with zipfile.ZipFile(ZIP, 'r') as old, zipfile.ZipFile(
                    temporary_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
                for info in old.infolist():
                    name = info.filename
                    if name in replacements:
                        new.write(replacements[name], name)
                        written.add(name)
                    elif name.endswith('/'):
                        new.writestr(info, b'')
                    else:
                        # Stream the large disc image instead of reading 700+ MB into RAM.
                        copied_info = copy.copy(info)
                        with old.open(info, 'r') as source, new.open(copied_info, 'w') as target:
                            shutil.copyfileobj(source, target, length=1024*1024)
                for name, path in replacements.items():
                    if name not in written:
                        new.write(path, name)

            with zipfile.ZipFile(temporary_zip) as check:
                names = check.namelist()
                assert len(names) == len(set(names)), 'Duplicate archive entries.'
                assert check.testzip() is None, 'ZIP integrity check failed.'
                packaged_config = check.read(PREFIX+'runtime/TM3Console.ini').decode('utf-8-sig')
                packaged_doc = check.read(PREFIX+'SYSTEM256_PRUEBA_ES.md').decode('utf-8')
                packaged_exe_hash = hashlib.sha256(check.read(PREFIX+'TM3Lobby.exe')).hexdigest()
                assert 'Resolution=1' in packaged_config and 'AudioLatency=' not in packaged_config
                assert 'ambas PC' in packaged_doc and 'vuelven a Software' in packaged_doc
                assert packaged_exe_hash == digest(EXE)
                assert all(PREFIX+'runtime/system256/'+name in names for name in required_assets)
                assert PREFIX+'sources/beetle_psx_system256_vulkan_source.zip' in names
                assert PREFIX+'licenses/LICENSE_libwinpthread.txt' in names
                assert any(name.startswith(PREFIX+'runtime/cores/') for name in names)
                result = dict(zip=str(ZIP), backup=str(BACKUP), bytes=temporary_zip.stat().st_size,
                              files=len(names), exe_sha256=packaged_exe_hash,
                              core_source_bytes=source_archive.stat().st_size,
                              zip_integrity=True, settings='1x / local audio, no artificial prebuffer',
                              automatic_vulkan=True, automatic_gpu_per_pc=True,
                              game_aspect='4:3', coordinated_software_fallback=True)
            temporary_zip.replace(ZIP)
            result['bytes'] = ZIP.stat().st_size
            print(json.dumps(result, indent=2, ensure_ascii=False))
        finally:
            if temporary_zip.exists():
                temporary_zip.unlink()


if __name__ == '__main__':
    main()
