"""Replace the portable ZIP's old game runtime with SYSTEM256, after backup."""
from pathlib import Path
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT/'dist/TM3Online_UI2_175_20261021'
ZIP = ROOT/'TM3Online_Portatil.zip'
BACKUP = ROOT/'TM3Online_Portatil_ANTES_SYSTEM256.zip'
ASSETS = DIST/'runtime/system256'
PREFIX = 'TM3Online_UI2_175_20261021/'


def main():
    assert ZIP.is_file() and zipfile.is_zipfile(ZIP)
    assert (ROOT/'diagnostics/system256_integration/lobby_result.json').is_file()
    result = json.loads((ROOT/'diagnostics/system256_integration/lobby_result.json').read_text())
    assert result['passed'] and result['start1'] and result['start2']
    exe = ROOT/'diagnostics/system256_latency_audio_qa/dist/TM3Lobby_Release.exe'
    assert exe.is_file() and exe.stat().st_size > 5_000_000
    ASSETS.mkdir(parents=True, exist_ok=True)
    for source, name in ((ROOT/'256mb system/game/TM3_SYSTEM256.bin','TM3_SYSTEM256.bin'),
                         (ROOT/'256mb system/game/TM3_SYSTEM256.cue','TM3_SYSTEM256.cue'),
                         (ROOT/'256mb system/runtime/beetle_psx_system256.dll','beetle_psx_system256.dll')):
        shutil.copy2(source, ASSETS/name)
    shutil.copy2(exe, DIST/'TM3Lobby.exe')
    config_path = DIST/'TM3Lobby.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    config['system256'] = {'enabled': True, 'assets': 'runtime/system256',
                           'input_delay_policy': 'adaptive_from_measured_peer_rtt',
                           'initial_delay_frames': 2}
    config['runtime']['variant'] = 'SYSTEM256 ABI6 + ICE confirmed input + CPU175'
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    video_config = DIST/'runtime/TM3Console.ini'
    if not video_config.exists():
        shutil.copy2(ROOT/'TM3Online_Lobby/runtime/TM3Console.ini', video_config)
    video_text = video_config.read_text(encoding='utf-8-sig')
    video_lines = video_text.splitlines()
    video_lines = [('Resolution=1' if line.startswith('Resolution=') else
                    'Smooth=0' if line.startswith('Smooth=') else line) for line in video_lines]
    video_lines = [line for line in video_lines if not line.startswith('AudioLatency=')]
    video_config.write_text('\n'.join(video_lines)+'\n', encoding='utf-8')
    doc = DIST/'SYSTEM256_PRUEBA_ES.md'
    doc.write_text('''# SYSTEM256 — prueba entre dos PC\n\n1. Extrae la carpeta completa en ambas PC.\n2. Abre TM3Lobby.exe en las dos y entra a la misma sala.\n3. Cuando ICE esté conectado, el anfitrión pulsa START.\n4. Usa la configuración de teclado y mandos guardada en runtime/TM3Console.ini.\n5. F11 alterna pantalla completa; Esc cierra la partida y vuelve al lobby.\n\nEl vídeo inicia en resolución interna 4× (hasta 1280×960), proporción 4:3 y\nfiltrado vecino más cercano. Mantén la misma configuración gráfica en ambas PC.\nEl core incluido renderiza por software; esta opción no activa Vulkan ni usa\nla GTX para rasterizar.\n\nEl lobby confirma que ambas instalaciones tengan el mismo BIN y core antes\nde jugar. Cloudflare publica salas y señalización; ICE lleva directamente\nlos controles cifrados. Esta versión no incluye un relay de juego: algunas\ncombinaciones de CGNAT pueden impedir la conexión. El margen de mando se\najusta según el RTT medido, desde dos cuadros cuando la ruta lo permite.\n''', encoding='utf-8')
    # Keep the portable guide aligned with the validated low-latency settings.
    doc.write_text("""# SYSTEM256 — prueba entre dos PC

1. Extrae la carpeta completa en ambas PC.
2. Abre TM3Lobby.exe en las dos y entra a la misma sala.
3. Cuando ICE esté conectado, el anfitrión pulsa START.
4. Usa la configuración de teclado y mandos guardada en runtime/TM3Console.ini.
5. F11 alterna pantalla completa; Esc cierra la partida y vuelve al lobby.

El vídeo inicia en resolución interna 1× (original), proporción 4:3 y filtrado
vecino más cercano. El core renderiza por software: Vulkan todavía no está
incluido. Cada PC produce y reproduce localmente el audio de su consola;
el audio no se envía por la red y conserva la configuración original.

Cloudflare publica salas y señalización; ICE intenta llevar directamente los
controles cifrados. Esta versión no incluye relay de juego: ciertas redes con
CGNAT todavía pueden impedir la conexión. El margen de mando se ajusta según
el RTT medido.
""", encoding='utf-8')
    sources = DIST/'sources/network'; sources.mkdir(parents=True, exist_ok=True)
    for name in ('system256_runtime.py','system256_bridge.py','lobby_client.py','lobby_entry.py'):
        shutil.copy2(ROOT/'network'/name, sources/name)
    if not BACKUP.exists():
        shutil.copy2(ZIP, BACKUP)
    elif not zipfile.is_zipfile(BACKUP):
        raise RuntimeError('The saved original backup is not a valid ZIP.')
    temporary = ZIP.with_name('TM3Online_Portatil_SYSTEM256.tmp.zip')
    with zipfile.ZipFile(BACKUP, 'r') as old, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
        replaced = set()
        for info in old.infolist():
            name = info.filename
            relative = name[len(PREFIX):] if name.startswith(PREFIX) else ''
            file = DIST/relative if relative else None
            if relative and file.is_file():
                new.write(file, name); replaced.add(relative)
            else:
                new.writestr(info, old.read(name))
        for file in DIST.rglob('*'):
            if file.is_file():
                relative = file.relative_to(DIST).as_posix()
                if relative not in replaced:
                    new.write(file, PREFIX+relative)
    with zipfile.ZipFile(temporary) as check:
        names = set(check.namelist())
        required = {PREFIX+'TM3Lobby.exe', PREFIX+'TM3Lobby.json', PREFIX+'SYSTEM256_PRUEBA_ES.md',
                    PREFIX+'runtime/system256/TM3_SYSTEM256.bin', PREFIX+'runtime/system256/TM3_SYSTEM256.cue',
                    PREFIX+'runtime/system256/beetle_psx_system256.dll'}
        assert required <= names, required-names
        assert PREFIX+'runtime/TM3Online.exe' in names
        assert any(n.startswith(PREFIX+'runtime/cores/') for n in names)
        assert any(n.startswith(PREFIX+'runtime/game/') for n in names)
        packaged_config = check.read(PREFIX+'runtime/TM3Console.ini').decode('utf-8-sig')
        assert 'Resolution=1' in packaged_config and 'AudioLatency=' not in packaged_config
    temporary.replace(ZIP)
    print(json.dumps({'zip':str(ZIP),'backup':str(BACKUP),'new_bytes':ZIP.stat().st_size,
                      'backup_bytes':BACKUP.stat().st_size,'files':len(names),'local_runtime_restored':True}, indent=2))


if __name__ == '__main__': main()
