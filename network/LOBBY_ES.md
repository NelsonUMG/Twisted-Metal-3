# Lobby TM3 Online

`EJECUTAR_TM3ONLINE.bat` ahora abre la interfaz de salas. `EJECUTAR_TM3ONLINE_DIRECTO.bat` conserva el acceso directo al juego sin lobby.

El paquete compilado se encuentra en `TM3Online_Lobby/TM3Lobby.exe`. `ABRIR_SALAS.vbs` lo prefiere automaticamente si existe. Ese paquete incorpora Python/Tk y el servidor dentro del ejecutable: no necesita instalar Python. `TM3Lobby.json` resuelve las rutas de su carpeta runtime y selecciona la variante SqrtMergeV4 + LinkBoundaryV1 de la prueba anterior. Conserva toda la carpeta al copiarlo a otro equipo.

Abre `ABRIR_SALAS.vbs` en cada equipo. Requiere Python 3 con Tkinter (incluido en el instalador de Windows). Crea un nombre, pulsa **Crear sala**; el otro jugador ve la sala automaticamente y pulsa **Unirse**. Con dos jugadores, el anfitrion pulsa **START**. El launcher comprueba los archivos en ambos equipos, abre el anfitrion, comprueba que su proceso escucha TCP 27888 y despues abre el invitado. No consume la conexion del juego para comprobar el puerto.

Al pulsar Crear sala se pide una descripcion de 1 a 100 caracteres. Aparece en su columna de la lista y en la ventana de la sala. Las peticiones antiguas sin descripcion usan el titulo automatico Sala de [usuario]. La version de fuentes necesita Python; el paquete .exe no.

La lista general y la sala son ventanas distintas. Crear o unirse abre automaticamente la ventana de esa sala con sus dos puestos y los roles de anfitrion/invitado. **START** esta dentro de la sala y solo se muestra al anfitrion; se habilita cuando hay dos jugadores. No hay boton Ver mi sala. La X de la sala solicita salir (o cerrar el anuncio si eres anfitrion) y termina exclusivamente el juego que este launcher haya iniciado para esa sala; el lobby general permanece abierto. Si se rompe la pareja al salir un jugador, se termina el proceso de juego asociado del otro equipo en su siguiente consulta al directorio. No se buscan ni se cierran otros juegos por nombre. Si el anfitrion sale o se pierde la conexion, se cierra la ventana de sala correspondiente.

Cada sala tiene chat de texto: escribe y pulsa **Enter** o **Enviar**. Solo sus miembros reciben los mensajes; quienes estan viendo anuncios no reciben el historial. Se muestran nombres y hora local, mas avisos de entrada/salida. Se conservan los ultimos 100 mensajes por sala en memoria, con un maximo de 500 caracteres por mensaje. Al cerrarse la sala se elimina su historial. El chat sigue disponible mientras el juego este abierto. El chat pasa por el directorio; no es un chat global ni mensajeria privada entre cuentas fuera de salas.

El perfil se guarda en `%LOCALAPPDATA%\TM3Online\Lobby\profile.json`. El directorio reserva el nombre de forma persistente; otro perfil no puede registrarlo, y el mismo perfil no puede conectarse dos veces simultaneamente. Conserva ese archivo para conservar tu identidad. Los nombres son unicos **en ese directorio**, no entre directorios independientes. Salas de dos humanos; los seis CPU se eligen dentro del juego.

## Red local

La busqueda usa UDP 27890. Si no encuentra un directorio, inicia uno local automaticamente (HTTP TCP 27890). Windows puede pedir acceso a la red para Python: permite la red privada. Todos los equipos necesitan llegar al mismo directorio; los broadcast no atraviesan subredes o algunas redes Wi-Fi con aislamiento. No se escribe la IP del anfitrion. El directorio detecta la direccion de cada conexion y comunica el destino al invitado.

El directorio local permanece abierto como proceso independiente. Al salir de una sala anfitriona se elimina su anuncio; al cerrar el launcher se cierra su sesion, o vence en unos 20 segundos si no pudo avisar. Cerrar el launcher no termina los juegos. Si dos equipos crean directorios al mismo tiempo pueden quedar separados: deja abierto el primero y reconecta el segundo.

## Internet: directorio comun pendiente de publicar

La busqueda LAN no descubre equipos de Internet. Para la lista compartida desde redes diferentes se incluye `lobby_server.py`, pero **no hay un servicio publico desplegado ni una URL inventada**.

El administrador ejecuta en un servidor accesible por ambos:

```text
python network/lobby_server.py --bind 127.0.0.1 --port 27890 --database /ruta/persistente/users.sqlite3
```

Tambien se incluye una imagen de despliegue. Desde la raiz del proyecto:

```text
docker build -f network/Dockerfile.lobby -t tm3-lobby network
docker run -d --name tm3-lobby --restart unless-stopped -p 127.0.0.1:27890:27890 -v tm3-lobby-users:/data tm3-lobby
```

El volumen conserva los usuarios; las salas y sesiones son temporales. Una sola instancia de directorio atiende a todos: cada cliente recibe **todas** las salas, incluidas las llenas y las que ya iniciaron partida. Cada sala tiene su propio limite de dos jugadores y Start independiente. No usar varias replicas independientes: dividirian las salas y las reservas de nombres. El servicio de nube y su cuenta todavia no estan contratados/configurados; esta imagen es preparacion para publicarlo, no evidencia de despliegue.

Se publica detras de un proxy HTTPS. El administrador copia `lobby_config.example.json` como `lobby_config.json` y configura la URL real en ambas distribuciones; tambien puede definir `TM3_LOBBY_URL`. El jugador solo ve salas y el boton Unirse. Si el servicio configurado falla no se crea un directorio local separado silenciosamente.

Este directorio resuelve registro, presencia, salas y Start. **No implementa NAT traversal ni relay del trafico de juego**: la conexion actual de TM3 sigue usando TCP y UDP 27888 hacia el anfitrion. Entre redes distintas necesita puertos accesibles, una VPN comun o un relay de juego que todavia no esta implementado. Detectar una IP publica no permite atravesar cualquier router/CGNAT. La prueba entre redes y el despliegue publico quedan pendientes.

## Runtime

Sin configuracion usa el ejecutable neutro, core y disco de `frontend/build/Release`. Para usar una variante de diagnostico, define las tres rutas `runtime` en `lobby_config.json`; las rutas relativas parten de la raiz del proyecto. Ambos equipos deben tener las mismas versiones del juego/core. No usar ejecutables renombrados Oscar/Sofia: fijan el rol antes de leer los argumentos.

El launcher no cambia el BIN, el core, los controles ni la velocidad del juego. START abre los dos procesos; no selecciona por si solo las opciones Online/Link Cable dentro del juego. No declara sincronizacion de partida hasta que la conexion propia del juego se complete.

## Simulacion de cuatro cuentas

```text
python network/simulate_four_accounts.py --output diagnostics/lobby_four_accounts
```

Crea un directorio HTTP temporal en loopback y cuatro perfiles independientes (Nelson, Oscar, Sofia y Alex). Comprueba que las cuentas que permanecen fuera de una sala ven los anuncios de todos los anfitriones; luego forma dos salas 2/2 y verifica el rechazo de un tercero, Start reservado al anfitrion, independencia entre salas y retirada de anuncios al salir el anfitrion. Los observadores ven las salas sin recibir la direccion de conexion del juego. Genera un informe Markdown y un JSON sin credenciales. No abre juegos, no modifica perfiles reales, no publica servicios y no constituye una prueba de NAT/CGNAT ni una medicion de latencia.

## QA: 69 casos

```text
python network/qa_lobby_69.py --output diagnostics/lobby_qa69/after
```

69 casos independientes con directorio, usuarios y puertos temporales. Cubren identidad persistente, nombres duplicados, sesiones, lista compartida, salas de dos plazas, solicitudes concurrentes, privacidad de observadores, permisos de Start, confirmaciones duplicadas/tardias, recuperacion por tiempo agotado y solicitudes HTTP invalidas. Los tiempos de expiracion se inyectan; no se espera a que transcurran ni se simula una red WAN. Los informes contienen resultados por caso, trazas de fallos y hashes SHA256 del codigo verificado. No prueban CGNAT real, latencia ni el arranque de los juegos.
