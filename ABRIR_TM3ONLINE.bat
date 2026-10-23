@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "TM3_DATA_DIR=%~dp0userdata"
if not exist ".python\pythonw.exe" (
  echo Falta el entorno Python local. Consulta docs/LOCAL_INDEPENDIENTE.md
  pause
  exit /b 1
)
if not exist "runtime\TM3Console.ini" copy /y "config\TM3Console.example.ini" "runtime\TM3Console.ini" >nul
start "" ".python\pythonw.exe" "network\lobby_entry.py"
