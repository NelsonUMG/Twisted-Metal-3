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
  Las recetas antiguas están retiradas en `legacy-source/distribution/`;
  el único punto de distribución nuevo es `tools/build_installer.py`.

La carpeta completa de Windows ahora incluye `runtime/`, `.python/` y
`assets/original/`, por solicitud del propietario. Los binarios grandes usan
Git LFS. Para obtener todos los archivos hay que clonar con Git LFS y ejecutar
`git lfs pull`; el ZIP de fuentes de GitHub puede contener sólo sus punteros.
Credenciales, ajustes personales y partidas siguen excluidos. Se conservan las
licencias de cada componente. Ver [carpeta independiente](docs/LOCAL_INDEPENDIENTE.md).

## Compilar y comprobar

Para ejecutar: Windows x64 y `ABRIR_TM3ONLINE.bat`, con el Python incluido.
Para reconstruir componentes nativos: compilador MinGW para los cores, Visual Studio C++
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

La Release [v0.2.1](https://github.com/NelsonUMG/Twisted-Metal-3/releases/tag/v0.2.1)
publica un manifiesto y archivos individuales verificados con SHA256. Requiere
una instalación existente con el nuevo actualizador; no incluye instalador inicial.

El lobby consulta una sola vez al abrir. Si hay una versión mayor, compara
los archivos instalados con el manifiesto, descarga sólo los diferentes y
muestra el progreso y sus nombres. «Reiniciar» cierra los procesos propios,
aplica los cambios con recuperación temporal y vuelve a abrir el lobby.
Se conservan ajustes personales y partidas. GitHub registra diferencias de código;
el cliente reemplaza archivos completos modificados, incluidos PY, DLL y EXE.

Para próximas publicaciones: actualizar VERSION, ejecutar QA, confirmar los cambios
y subir un tag vX.Y.Z coincidente. El workflow usa windows-latest y compila los
assets mediante tools/build_installer.py --runtime runtime --stage-only.
El Setup inicial continúa siendo un trabajo separado que requiere Inno Setup.
No hay tokens de GitHub en los clientes. Ver docs/FILE_UPDATE_QA.md.

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
