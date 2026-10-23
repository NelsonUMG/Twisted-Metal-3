# TM3 Online — Lobby y consola

Abre **TM3Lobby.exe**. No requiere instalar Python. Conserva el ejecutable, TM3Lobby.json y la carpeta runtime juntos; para otro equipo copia la carpeta completa.

Al crear sala se pide una descripción (1 a 100 caracteres). Los otros jugadores la ven en la lista. La sala se abre automáticamente con su chat, dos plazas y Start exclusivo del anfitrión. Start abre nuestra consola propia en ambos equipos.

## Juego incluido en este paquete local

Disco **SqrtMergeV4**, core **LinkBoundaryV1** con **PacingV1**, y espera **LinkWakeV1**: mismos disco y core del contexto de prueba `SqrtMergeV4_PacingV1_LinkBoundaryV1_LinkWakeV1_20261019_170456_605_21305ed3`. El frontend ahora incluye nuestra interfaz nativa de menús; no se ha migrado a DuckStation. Los hashes figuran en BUILD_MANIFEST.json.

La consola tiene menús oscuros Sistema, Ajustes, Vista, Herramientas y Ayuda. Ajustes usa categorías laterales, páginas con grupos de controles y ayuda inferior. Las opciones disponibles incluyen aspecto de imagen, suavizado de presentación, volumen/silencio, teclado, mando XInput, atajos y opciones de ventana. Las funciones de otro motor que no están implementadas aparecen deshabilitadas. F11 alterna pantalla completa y F10 captura una imagen de forma predeterminada; se pueden cambiar en Atajos. Los ajustes locales se guardan automáticamente en runtime/TM3Console.ini. En modo local, Pausar detiene/reanuda la emulación. Pausar el emulador y reiniciar localmente se deshabilitan durante un enlace; dentro de una partida enlazada se usa el Start del juego.

Los iconos y separadores se dibujan sin depender de fuentes de símbolos. Las páginas y el título no publican rutas completas ni datos internos de diagnóstico o conexión. Las estadísticas están desactivadas por defecto; al activarlas solo se añaden FPS al título. Los registros técnicos siguen en disco para revisión, pero no tienen un acceso en los menús de juego.

Los logs del diagnóstico se guardan por ejecución en `%LOCALAPPDATA%\TM3Online\Lobby\runs`. Los perfiles se conservan en `%LOCALAPPDATA%\TM3Online\Lobby`. Las tarjetas usan runtime/saves_lobby_host y runtime/saves_lobby_client.

Se mantienen las opciones Online/Link Cable y la selección de CPU dentro del juego. El diagnóstico añade carga; este paquete no demuestra mejoras de velocidad. No incluye el motor gráfico, logros o posprocesado de DuckStation.

En Gráficos puedes elegir resolución interna real 1x, 2x o 4x, además de proporción y suavizado. Más resolución puede reducir el rendimiento; 1x sigue siendo el valor predeterminado. PGXP y el panorámico 16:9 utilizan funciones del motor existente y solo se permiten en modo local; pueden producir errores visuales según la escena. En Mandos, pulsa un campo y después la tecla o botón que quieras asignar. Esc cancela y clic derecho borra. Se admiten teclas especiales y mandos XInput, incluidos gatillos y palancas como entradas digitales. En Audio puedes seleccionar la salida; si falla se utiliza la predeterminada.

La búsqueda automática es local. Para salas por Internet hay que publicar un directorio común y configurar directory_url en TM3Lobby.json. La conexión a través de NAT/CGNAT del tráfico del juego sigue pendiente. Los archivos del juego corresponden a la copia local proporcionada por el usuario.

La consola reconoce los núcleos físicos y usa preferencias de ejecución distintas para emulación, presentación y red, sin desactivar Hyper-Threading ni limitar la afinidad del proceso. La emulación solicita la clasificación multimedia Games de Windows si está disponible. Dibujar o guardar una captura ya no bloquea el búfer que necesita la emulación. Los roles efectivos se registran en threading.jsonl junto a los demás registros, fuera de la interfaz. Estas mejoras de planificación no garantizan una velocidad concreta y no dividen la simulación MIPS entre doce hilos.
