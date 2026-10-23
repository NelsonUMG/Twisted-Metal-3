# Carpeta local completa

Esta copia incluye las fuentes de Git y, mediante Git LFS,
`runtime/` con el juego online/local, DLL y configuración personal; `.python/`
con el intérprete, biblioteca estándar y todas las dependencias Python; y
`assets/original/` con la imagen original para mantenimiento.

Abrir `ABRIR_TM3ONLINE.bat` inicia el lobby desde esta carpeta.
La ruta de Python es relativa. El archivo python314._pth lo aísla de otras
instalaciones de Python y del antiguo entorno externo.

```powershell
.python/python.exe -m unittest discover -s network -p 'test_*.py'
.python/python.exe network/system256_cable_p2p_qa.py --output diagnostics/local-independent --timeout 180
.python/python.exe tools/build_installer.py --runtime runtime --stage-only
```

Usar siempre `.python/python.exe -m pip` y `.python/python.exe -m PyInstaller`.
Los lanzadores de la antigua carpeta Scripts no se copian porque contienen
rutas absolutas al entorno anterior.

Los archivos del juego, DLL e intérprete se incluyen en Git LFS por solicitud
del propietario. Para una copia completa: instalar Git LFS, clonar y ejecutar
`git lfs pull`. Los ajustes personales, partidas y credenciales no se suben.
`ABRIR_TM3ONLINE.bat` guarda el perfil/cache del lobby en `userdata/` local
y genera el INI desde config/TM3Console.example.ini si aún no existe.
Windows, los controladores
de audio/vídeo y las herramientas nativas de compilación siguen siendo requisitos
externos. Inno Setup sigue siendo necesario para generar el instalador.
