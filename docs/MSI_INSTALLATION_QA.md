# Instalador MSI para prueba en otra PC

Construcción local con WiX 6.0.2, .NET SDK y extensión WixToolset.UI.wixext 6.0.2. El usuario final no necesita Python, .NET SDK ni WiX: TM3Lobby.exe y TM3Update.exe son ejecutables congelados.

```powershell
dotnet tool install wix --tool-path build/toolchain/wix --version 6.0.2 --allow-roll-forward
build/toolchain/wix/wix.exe extension add -g WixToolset.UI.wixext/6.0.2
.python/python.exe tools/build_msi.py --include-game
```

El MSI completo incluye los archivos locales BIN/CUE de runtime/game y runtime/system256, además de los motores, configuraciones de distribución y licencias. No incorpora perfil del lobby, credenciales, partidas, dispositivo de audio personal ni un BIOS externo. Los núcleos incluyen OpenBIOS; dejar BIOS en Automático permite el arranque sin aportar un firmware externo. Esta variante completa es un artefacto local para la prueba solicitada; los archivos del juego no se añaden al canal público de Releases ni a su manifiesto de actualización.

Instala por usuario en LocalAppData/Programs/TM3Online, permite elegir carpeta y crea accesos directos. El lobby realiza una sola consulta de actualización por ejecución; si ya coincide con la Release publicada, no muestra descarga. Una actualización futura descarga sólo los archivos de aplicación diferentes y ofrece Reiniciar. Los BIN/CUE, INI y partidas quedan fuera del protocolo de actualización.

La selección de vídeo es automática. Si cualquiera de los dos peers no tiene Vulkan disponible o no puede inicializarlo, se negocia software para ambos. QA con el ejecutable del MSI y un peer sin componentes Vulkan: 600 ticks cada uno, TIME/RNG mismatch cero, ambos software, aproximadamente 29.94 ticks/s en esta PC. No acredita el rendimiento de una laptop distinta ni WAN.

Evidencias locales del instalador: build/msi/install.log, qa_result.json (69 archivos verificados, una consulta automática, segunda consulta bloqueada y prueba ICE del ejecutable instalado); full-install.log, full-qa-result.json (archivos de juego íntegros, ajustes y partida conservados, runtime localizable). Se detectó durante QA que la desinstalación no recordaba una ruta personalizada; el constructor añade persistencia de INSTALLFOLDER para resolverlo.

En la segunda PC: instalar, abrir TM3Lobby.exe, configurar nombre, revisar el renderizador elegido y sonido/teclado/mando; conectar la sala con la primera PC, iniciar en ambos órdenes, cancelar y reintentar, regresar al menú y jugar otra partida. Confirmar audio físico, imagen y estabilidad durante mapas completos. Esas verificaciones siguen pendientes: este paquete se entrega para prueba y no implica QA global al 100% ni distorsión Vulkan resuelta.

Resultado final: MSI completo instalado y desinstalado con código 0, ruta personalizada recordada, ejecutable retirado de esa ruta, INI y partida de prueba conservados. Los cuatro BIN/CUE coinciden en SHA256 con los originales y --check-runtime del EXE instalado confirma runtime y GUI correctos. Archivo local: dist/TM3Online-0.2.1-x64-Completo.msi; tamaño y digest en MSI_INSTALLATION_QA_20261023.json y en el archivo .msi.sha256 junto al instalador. No se subió este MSI con juego a GitHub Releases.

Selector actual: árbol clásico SHBrowseForFolder, con Escritorio virtual como raíz y carpetas desplegables, tal como la referencia visual solicitada. Reemplaza tanto el explorador moderno como la lista de seis ubicaciones. La carpeta seleccionada recibe la subcarpeta TM3Online; si ya se selecciona TM3Online, no la duplica. Cancelar conserva la ruta existente. Se validan rutas Unicode, carpetas habituales, rutas arbitrarias, raíz de unidad e índices/búferes inválidos. El diálogo sólo admite destinos del sistema de archivos. La revisión visual automática de msiexec sigue bloqueada por la política del controlador de ventanas; no se intentó automatizar por otra vía. Artefacto actual: dist/TM3Online-0.2.1-x64-Completo-ArbolCarpetas.msi.
