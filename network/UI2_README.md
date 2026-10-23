# TM3 Online — UI2 / semi-production

Open **TM3Lobby.exe**, then create/join a room or select **Play locally**.
The manual P2P-code window has been removed. The shared-directory mode uses the
normal room list: Create room, Join, START; ICE negotiation is automatic.
See **SALAS_AUTOMATICAS_ES.md**. The Cloudflare directory is publicly deployed,
with verified HTTPS/WSS, and its address is built into this portable. Update
BOTH PCs. No pasted invitation codes or player-side server setup are needed.
Explicitly choosing an empty Internet address retains LAN-only rooms. Some
restrictive CGNAT combinations still need a gameplay relay; real cross-ISP
gameplay is not yet validated.
After START establishes the peer link, the room and lobby show live peer ping
(round-trip milliseconds), a 30-sample average and RTT variation. Probes run
every 2 seconds on the encrypted peer control channel, not through Cloudflare.
Old samples are marked stale after 6 seconds. This is not total input lag.
English is the default. Choose English/Español in the lobby or General settings.

System → Close game unloads the disc and audio, leaving the emulator open.
System → Open game (Ctrl+O) loads another PS1 image. It never deletes your disc.
Exit closes the emulator. Changing discs during a linked session is disabled.

Controller settings include a PS1 diagram and keyboard/XInput assignments.
Graphics settings configure this software renderer, not DuckStation's hardware
backends. Audio supports device, volume and 20/40/80 ms buffering. BIOS settings
accept your own 512 KiB BIOS; selection applies on the next game load.

Audio reserve update: new installations default to an 80 ms queue. Playback
starts after approximately 40 ms has accumulated and rebuilds that reserve
after starvation. This is not time stretching and does not fix sustained slow
emulation. Existing explicitly selected audio settings are preserved.

TM3 uses the tested development setting of 175% CPU budget; other images use
100%. No automatic diagnostic scan is enabled. This remains semi-production:
long online sessions and compatibility with other PS1 titles need real play tests.
Distribute only game/BIOS images you have permission to distribute.

Online session update (protocol 7): update BOTH PCs. The room host always owns
in-game role 2 (shared options); the guest owns role 1, regardless of who selects
YES first. Linked games wait for the transport before booting, and the lobby
requires the connection flag inside the game before announcing the match.
If connection is not confirmed, it reports a startup failure rather than
silently presenting local play as an online session.

System -> Cancel online game / Return to main menu, or Escape, cancels for both
players. A Triangle-confirmed return from a linked menu, leaving the room, or a
lost peer also returns the other game. Native menu returns preserve the link;
a failed native return or a lost peer can fall back to reloading the disc.
The emulator stays open. Closing the entire lobby
closes its owned games and its local directory server. A game launched by the
lobby also exits if its owning lobby process disappears.

Triangle cancellation fix: a normal transition after selecting vehicles is not
cancellation. Returning from a linked menu requires an actual Triangle press.
The other game follows its Triangle/back menu flow while preserving the linked
transport, so online play remains available from the main menu. A failed native
menu return or a genuinely lost connection can still fall back to reloading the
disc locally; session state records that reason separately.

## Español

### Prueba experimental: dos jugadores por PC (2+2)

En cada PC, abre Ajustes -> Mandos. En el selector superior elige
**Jugador 2 / Puerto 2**, marca **Activar jugador local 2** y asigna su mando.
En automático se usan mandos físicos distintos; puedes elegirlos explícitamente.
Si el jugador 1 usa teclado y el jugador 2 el único mando, desmarca
**Activar mando** en el puerto 1 para dejarlo disponible al puerto 2.
El jugador 1 conserva sus asignaciones anteriores. El jugador 2 tiene teclado
independiente: flechas, Enter para Start y teclado numérico (1=X, 3=Círculo,
4=Cuadrado, 5=Triángulo). Todas sus asignaciones se pueden cambiar.

Activa el segundo jugador antes de configurar la partida en TM3. La sala sigue
uniendo dos PC; dentro de cada una se conectan dos jugadores. El anfitrión de
la sala mantiene el rol 2 y el invitado el rol 1: son roles de consola, no el
número de jugador local. Configura el número de jugadores locales en el juego
y comprueba que ambos jugadores de cada PC puedan elegir vehículo.

Se verificaron puertos independientes, persistencia, transporte de datos 2+2,
arranque enlazado con dos puertos por emulador y cancelación. Falta validar
una carrera real completa con cuatro humanos. Este modo es experimental;
el segundo puerto está desactivado por defecto. No requiere Multitap para
dos mandos por consola y no modifica el BIN activo.

Abre **TM3Lobby.exe**. **Play locally / Jugar local** no requiere otra computadora.
Elige Español arriba del lobby o en los ajustes generales del emulador.
**Cerrar juego** descarga el disco sin cerrar el emulador ni borrar el archivo.
**Abrir juego** permite cargar otra imagen de PS1. **Salir** cierra la aplicación.
Se conservan las partidas y preferencias de la instalación existente al actualizar.
La configuración de video corresponde al renderizador por software disponible;
no es una copia completa de DuckStation. Sigue siendo una versión de prueba.
