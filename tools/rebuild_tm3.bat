@echo off
setlocal
if "%~1"=="" (
  echo Uso: rebuild_tm3.bat RUTA_A_TM3.xml
  exit /b 1
)
where mkpsxiso.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: mkpsxiso.exe no esta en PATH ni en esta carpeta.
  exit /b 2
)
mkpsxiso.exe "%~1"
endlocal
