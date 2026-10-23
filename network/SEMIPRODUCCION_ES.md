# TM3 Online — Semiproducción 175% · 21/10/2026

Extrae el ZIP completo en una carpeta con permiso de escritura y abre TM3Lobby.exe.
No requiere Python instalado. No ejecutes el programa dentro del ZIP.

Jugar local abre el juego sin una sala ni otra computadora. Usa las tarjetas
runtime/saves_lobby_local. Cierra el juego antes de iniciar otra partida.
Para jugar enlazado, ambos equipos deben tener esta misma versión: crea una
sala, espera al segundo jugador y pulsa START como anfitrión. Permite el acceso
del lobby y del juego en el firewall de tu red privada.

El presupuesto CPU emulado queda fijo al 175%, incluso al ejecutar la consola
directamente. No es overclock del procesador físico. El disco SqrtMergeV4 no
se modificó. No mezcles esta versión con los paquetes anteriores al 100/150%.

Se desactivaron los perfiles, escaneos y trazas automáticas de diagnóstico.
Se conserva el protocolo y la comprobación de sincronización del juego.
No se incluyen capturas, logs históricos, tarjetas de prueba ni herramientas
de ingeniería inversa. Tus partidas nuevas se guardan en la carpeta runtime.
Los ajustes se guardan en runtime/TM3Console.ini; F11 alterna pantalla completa.

Esta es una entrega de semiproducción: el 150% tuvo una captura local enlazada
cercana a 30 TIME/s; eso NO valida el 175% durante partidas largas ni Internet.
Si observas problemas, cierra ambos juegos y conserva sus tarjetas. No hay
garantía de 30 constantes ni de equivalencia temporal con la consola original.

El descubrimiento automático de salas funciona en la red local. Para equipos
en redes distintas se necesita un directorio común (directory_url en
TM3Lobby.json) y conectividad del juego TCP/UDP 27888. NAT/CGNAT no se resuelve
automáticamente con este paquete. El directorio local usa el puerto 27890.

Distribuye los archivos del juego/BIOS solamente donde tengas autorización.
Se conservan los avisos de licencia y las fuentes del core y la consola en
sources y licenses. BUILD_MANIFEST.json identifica los archivos por SHA256.
