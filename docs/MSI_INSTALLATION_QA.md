# Instalador MSI para prueba en otra PC

La entrega actual es `../TM3Online-0.2.1-Setup.exe`: al abrir permite elegir Español o English. Contiene un único MSI completo y una transformación inglesa de su interfaz; no cambia el idioma del lobby ni del emulador. El selector clásico de carpetas también traduce su indicación. El Setup y su checksum permanecen fuera del checkout y no se publican en GitHub ni en el canal de actualizaciones.

Para reconstruir la entrega bilingüe, generar `build/msi/TM3Online-es.msi` y `build/msi/TM3Online-en.msi` usando `tools/build_msi.py --include-game --culture es-es|en-us --output ...`, generar `build/msi/English.mst` con `wix msi transform -t language` desde el MSI español al inglés, y ejecutar `.python/python.exe tools/build_setup.py`. Ambos MSI comparten ProductCode; la transformación sólo localiza el instalador. QA: extracción real del Setup en ambos idiomas con SHA256 correcto, ProductLanguage 3082/1033, botones &Siguiente/&Next y tabla File idéntica antes/después de aplicar la transformación. Pruebas del selector de carpetas y exclusión de instaladores del actualizador aprobadas. La automatización visual de msiexec permanece bloqueada por la política del controlador; estos resultados verifican extracción y tablas del paquete.

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

Ubicación final solicitada: ../TM3Online-0.2.1-x64-Completo.msi, junto a Twisted-Metal-3 y fuera del checkout. El constructor genera por defecto los MSI en esa carpeta padre y deja .wixpdb en build/msi. Los MSI y sus auxiliares están excluidos explícitamente de Git; el generador de actualizaciones rechaza MSI/MSP/MSM, símbolos WiX y TM3Online-Setup.exe. El workflow publica únicamente el manifiesto y los blobs citados por él. Se comprobó que la Release v0.2.1 tiene 69 assets y ningún instalador. La ubicación local del MSI no participa en el actualizador de los clientes.
