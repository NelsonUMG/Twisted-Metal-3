# Reducción de trabajo de interfaz y presentación

Cambios locales pendientes de publicación. Base: 048a2fd. No se cambian núcleos, CPU175, RAM, protocolo de cable, resolución, entrada, frecuencia de emulación ni comportamiento del audio. El presupuesto real actual es 175 %, y se conserva.

Las tablas conservan sus filas, selección y orden. Una respuesta idéntica del directorio no realiza operaciones Tk sobre las filas; una modificación usa Treeview.set únicamente sobre las celdas afectadas. Añadir o retirar una sala sí inserta o elimina su fila. Los textos traducidos participan en la comparación. Las pruebas incluyen salida/entrada de jugadores, cambio de idioma, reordenación y selección conservada en un Treeview real.

En software se omite exclusivamente la presentación repetida de la misma instantánea de vídeo. Cada instantánea nueva sigue presentándose; redimensionar, exponer la ventana o cambiar el filtro obliga a actualizar la imagen. No se omiten pasos de emulación. El archivo de ajustes se consulta cuatro veces por segundo en lugar de hasta 120; el bucle de eventos sigue a 120 Hz y los ajustes continúan aplicándose durante la sesión, con hasta 250 ms de espera para detectar el cambio.

Medición de CPU mediante psutil, sumando user+system de los procesos hijos y muestreando cada 200 ms. Escenario: dos procesos, ICE/DTLS/SCTP real en esta PC, grabación de entradas y 600 ticks de gameplay por consola, resolución 1x. No es una prueba de WAN ni del Core Duo del usuario.

| Medición | Antes | Después |
| --- | ---: | ---: |
| CPU de 2.000 actualizaciones idénticas del lobby | 1,547 s | 1,344 s |
| CPU acumulada de dos motores software, fuente | 108,078 s | 80,000 s |
| Duración de esa ejecución software | 69,521 s | 69,492 s |
| Velocidad por consola | 29,970 / 29,880 ticks/s | 29,971 / 29,902 ticks/s |

El ahorro observado fue aproximadamente 13 % en la tarea del lobby y 26 % en el escenario software. Es una comparación individual en esta máquina, no una garantía para otro procesador. La ejecución fuente exploratoria incluía una variación de espera del audio en reposo; se retiró de la versión final para conservar el comportamiento original del audio.

El ejecutable final también completó el mismo escenario software: 600 ticks por consola, 29,971/29,908 ticks/s y cero desajustes TIME/RNG. CPU total 78,172 s incluyendo los procesos del cargador de PyInstaller y 74,916 s de duración. Esa cifra incluye arranque/extracción y no constituye una comparación de arranque idéntica con las pruebas fuente. Se observaron 0/6 underruns de audio; no se afirma haber eliminado los cortes. Los hashes de RAM completos varían entre ejecuciones: se comprueban TIME/RNG del intercambio, no identidad byte por byte de toda la RAM.

Vulkan también completó ambas ejecuciones a unos 30 ticks/s, sin desajustes TIME/RNG. La mejora principal de presentación repetida afecta a software; no se promete el mismo ahorro en Vulkan.

Verificación: suite inicial de 168 pruebas aprobada, seguida de 47 pruebas de interfaz/celdas tras el refinamiento final. Informes detallados locales en build/performance-summary.json y build/performance-*/integration/result.json. El ejecutable completo local está en build/local-app/TM3Lobby.exe; build/payload continúa reservado para publicar archivos de aplicación sin BIN/CUE. No se ha publicado esta optimización.
