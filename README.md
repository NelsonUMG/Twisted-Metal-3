# TM3 Online — SYSTEM256

Proyecto Windows para Twisted Metal III online mediante WebRTC P2P. Cada PC
ejecuta una consola con 256 MiB de RAM emulada. El anfitrión tiene rol 2 y el
invitado rol 1. Cloudflare publica salas y señalización; el cable del juego
cruza el DataChannel fiable de WebRTC.

Este repositorio es ahora la fuente de trabajo. No se distribuyen paquetes
WinRAR ni se generan respaldos ZIP. Git versiona las fuentes; GitHub Releases
distribuye instaladores. Un commit no actualiza las instalaciones por sí solo.

## Directorios

- `network/`: lobby, configuración, actualizador, IPC y cable P2P en producción.
- `256mb system/src/`: adaptador real libretro y herramientas QA del core.
- `256mb system/core_source/`: fuentes completas del core software de 256 MiB.
- `cores/beetle-vulkan/`: fuentes completas del core Vulkan modificado.
- `legacy-source/console/`: frontend local original recuperado de console.zip.
- `legacy-source/core_cpu175/`: fuente del core local distribuido anteriormente.
- `config/`: ajustes de distribución, sin el dispositivo de audio personal.
- `installer/`: instalador Inno Setup con elección de directorio.
- `tools/`: herramientas de construcción, parches y antecedentes de ingeniería.
  Los scripts antiguos `package_*` quedan como fuentes históricas; el único
  punto de distribución nuevo es `tools/build_installer.py`.

No se incluyen imágenes del juego, BIOS, ejecutables, credenciales, partidas,
entornos Python ni compilaciones. Se conservan las licencias de cada componente.

## Compilar y comprobar

Windows x64, Python 3.14, compilador MinGW para los cores, Visual Studio C++
para el frontend local y el presentador Vulkan, e Inno Setup 6 para instalar.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-build.txt
$env:PYTHONPATH='network'
.venv/Scripts/python -m unittest network.test_system256_peer_cable network.test_lobby_client network.test_release_updater
```

Los cores incluyen sus Makefiles y COPYING. La configuración de CPU/RAM
específica está en libretro.c; no sustituirlos por un core Beetle estándar.
La aplicación online se congela desde `installer/lobby.spec`, que no depende
de rutas diagnostics ni del checkout exterior.

```powershell
python tools/build_installer.py --runtime C:/ruta/instalacion/runtime --iscc C:/ruta/Inno/ISCC.exe
```

El constructor usa una lista explícita de DLL y ejecutables; excluye imágenes
del juego y datos personales. Genera `dist/TM3Online-Setup.exe` y SHA256SUMS.txt.
El instalador permite elegir carpeta, conserva el INI existente y proporciona
desinstalación y accesos directos. Una instalación nueva puede importar los
archivos online compatibles desde `runtime/system256` de la instalación anterior.
Los archivos del juego pertenecen al usuario y no viajan en Releases.

## Publicación y actualización

1. Cambiar `VERSION`, ejecutar QA y guardar los cambios en Git.
2. El runner Windows privado etiquetado `tm3-release` debe tener Python, Inno,
   `gh`, `TM3_RELEASE_RUNTIME` y `TM3_ISCC` configurados.
3. Subir un tag `vX.Y.Z` que coincida con VERSION. El workflow crea la Release
   con `TM3Online-Setup.exe`; GitHub proporciona el SHA256 del asset.
4. El lobby consulta Releases al abrir y mediante «Buscar actualizaciones».
   Solicita instalar sólo si hay una versión mayor; verifica tamaño y SHA256
   antes de ejecutar el instalador en la carpeta actual.

No hay tokens de GitHub en clientes. Un repositorio privado requiere un canal
de descargas público separado o autenticación adicional; el actualizador usa
la API pública. No publicar versiones antes de validar el instalador completo.

## QA online

```powershell
$env:TM3_QA_ASSETS='C:/ruta/instalacion/runtime/system256'
python network/system256_cable_p2p_qa.py --output diagnostics/online-baseline
python network/qa_role_order.py --output diagnostics/online-order --timeout 260
```

Son dos procesos con ICE/DTLS/SCTP real. Si corren en una PC, la ruta sigue
siendo local; no certifican una conexión entre casas. Dummy audio/vídeo
valida generación y render pero no audibilidad ni apariencia física.
El ciclo completo de todos los mapas y la siguiente partida todavía requiere
evidencia de extremo a extremo. Ver `docs/MIGRATION_QA.md`.
