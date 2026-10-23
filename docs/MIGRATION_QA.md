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
