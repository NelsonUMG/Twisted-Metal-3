# Migración a GitHub e instalador — 2026-10-23

Origen: TM3Online_Prototype. Destino: NelsonUMG/Twisted-Metal-3.
SOURCE_IMPORT.json registra SHA256 de las fuentes importadas inicialmente.
Los cambios posteriores al import se registran mediante Git.

Se preservaron ambas variantes del core SYSTEM256, frontend local, core local,
parches, configuración del lobby y fixture de entradas por frame. Los archivos
binarios del juego y los dispositivos de audio personales quedan fuera de Git.

El actualizador usa únicamente GitHub Releases estables con tags vX.Y.Z,
un asset TM3Online-Setup.exe y SHA256 publicado por GitHub. El instalador
conserva el INI y no borra saves, juego ni configuración al actualizar.

Pendiente: compilación/ejecución real de Inno Setup (la instalación del compilador
fue rechazada por revisión automática), configurar runner privado de Releases,
prueba con una Release real, actualización interrumpida y conservación de datos,
retorno tras todos los mapas y nueva partida, audibilidad en PC remota y WAN real.
Estos pendientes impiden llamar a esta migración una distribución final validada.

Los ZIP y respaldos se eliminan sólo después de comprobar que sus fuentes únicas
están importadas y de confirmar que el commit está también en origin.

La importación de fuentes quedó confirmada en origin/main (commit inicial 05704d5).
En esa primera fase la revisión automática rechazó eliminar ZIP/RAR e instalar
Inno Setup. Posteriormente el usuario amplió expresamente la consolidación:
se copiaron juego, DLL y Python al repositorio, se probaron y se subieron mediante
Git LFS (1f2d8ae y 22a5420). La limpieza posterior autorizada eliminó 57 elementos
externos, incluidos los ZIP y la instalación antigua. Sólo queda el repositorio
con su carpeta contenedora. El compilador Inno Setup sigue pendiente.

Resultados medidos en docs/ONLINE_QA_20261023.json. Se detectó y corrigió la
escritura simultánea de status entre los hilos de rol y UI. La entrada frozen
captura los fallos del motor y preserva su informe para que una desconexión
esperada no abra el diálogo genérico de excepción de PyInstaller.

La ejecución posterior a la limpieza usa exclusivamente `.python/python.exe`
y `runtime/` internos. Lobby, Cloudflare, RTT y P2P se comprobaron de nuevo;
ambas consolas completaron 600 ticks sin diferencias TIME/RNG. La prueba nativa
local sólo verifica arranque y cierre normal. Durante la repetición de unittest
se detectó Tcl_AsyncDelete: el arnés retenía ciclos de widgets destruidos que
podían recogerse desde hilos de P2P. Su tearDown ahora cancela timers, elimina
referencias y recoge esos ciclos en el hilo propietario. La suite completa
terminó posteriormente con 120 pruebas y código de salida 0.
Ver docs/STANDALONE_QA_20261023.json y docs/LOCAL_INDEPENDIENTE.md.
