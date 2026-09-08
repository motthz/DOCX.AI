@echo off
REM ======================================================================
REM  MaintenanceAI - AVVIO DIRETTO
REM  Da usare DOPO aver lanciato INSTALLA_E_AVVIA.bat almeno una volta
REM  (ambiente virtuale, runtime e modello gia' pronti).
REM ======================================================================
setlocal EnableExtensions
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
title MaintenanceAI

set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERRORE] Ambiente virtuale .venv non trovato.
    echo          Lanciare INSTALLA_E_AVVIA.bat la prima volta.
    pause
    exit /b 1
)

set "LLAMA_EXE=%PROJECT_DIR%runtime\llama\llama-server.exe"
if not exist "%LLAMA_EXE%" (
    echo [ATTENZIONE] llama-server.exe mancante.
    echo          Rilancia INSTALLA_E_AVVIA.bat per ripristinare runtime e modello.
    pause
)

set "PYTHONPATH=%PROJECT_DIR%src;%PROJECT_DIR%"
"%VENV_PY%" -m maintenance_ai.main
set "EXIT_CODE=%ERRORLEVEL%"
if %EXIT_CODE% NEQ 0 (
    echo.
    echo Applicazione terminata con codice %EXIT_CODE%.
    pause
)
endlocal
exit /b %EXIT_CODE%
