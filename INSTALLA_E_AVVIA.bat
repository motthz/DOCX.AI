@echo off
REM ======================================================================
REM  MaintenanceAI - ISTRUZIONI PER L'AVVIO DOPO CLONE GITHUB
REM  Entry point per utente che ha clonato la repo su un PC nuovo.
REM  Cosa fa in ordine (tutto automatico):
REM    1. Controlla che sia installato Python 3.11+; se NON lo trova,
REM       prova a installarlo con winget.
REM    2. Crea l'ambiente virtuale .venv e installa le dipendenze.
REM    3. Esegue scripts/download_runtime.ps1 per scaricare
REM       llama-server.exe (runtime locale) e il modello Qwen3 1.7B GGUF.
REM    4. Avvia l'applicazione da sorgente (python -m maintenance_ai).
REM ======================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
title MaintenanceAI - Installazione e avvio
cls

echo.
echo ============================================================
echo   MaintenanceAI  -  Installazione e Primo Avvio
echo ============================================================
echo   Cartella progetto: %PROJECT_DIR%
echo.

REM ------------------------------------------------------------
REM 1. Python disponibile? Se no, tentativo winget
REM ------------------------------------------------------------
set "PY_CMD="
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        if not defined PY_CMD set "PY_CMD=%%I"
    )
)
if not defined PY_CMD (
    echo [1/5] Python non trovato. Tento installazione automatica via winget...
    where winget >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo       Esecuzione: winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        if !ERRORLEVEL! EQU 0 (
            echo       Installazione completata. Aggiorno PATH...
            set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
            for /f "delims=" %%I in ('where python 2^>nul') do (
                if not defined PY_CMD set "PY_CMD=%%I"
            )
        ) else (
            echo.
            echo [ERRORE] winget non e' riuscito a installare Python.
            echo          Per favore installa manualmente Python 3.12 x64 da:
            echo          https://www.python.org/downloads/release/python-3120/
            echo          SPEGNI il flag "Add Python to PATH" OFF per sicurezza,
            echo          anzi TOTALMENTE ACCESO (consigliato spunta in basso).
            echo          Poi rilancia questo file.
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo.
        echo [ERRORE] winget non disponibile e Python non e' installato.
        echo          Installa manualmente Python 3.12 x64 (con pip e tcl/tk).
        echo.
        pause
        exit /b 1
    )
)
echo [1/5] Python OK: "%PY_CMD%"
for /f "delims=" %%V in ('"%PY_CMD%" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2^>nul') do echo       Versione: %%V

REM ------------------------------------------------------------
REM 2. Ambiente virtuale e dipendenze
REM ------------------------------------------------------------
set "VENV=%PROJECT_DIR%.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
echo [2/5] Ambiente virtuale "%VENV%"...
if not exist "%VENV_PY%" (
    echo       Creazione .venv...
    "%PY_CMD%" -m venv "%VENV%"
    if errorlevel 1 ( echo [ERRORE] creazione venv fallita. & pause & exit /b 1 )
)
echo       Upgrade pip e dipendenze...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel >nul 2>&1
"%VENV_PY%" -m pip install -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 ( echo [ERRORE] installazione requirements.txt fallita. & pause & exit /b 1 )

REM ------------------------------------------------------------
REM 3. Verifica se llama-server.exe e modello ci sono
REM ------------------------------------------------------------
set "LLAMA_EXE=%PROJECT_DIR%runtime\llama\llama-server.exe"
set "MODELLO=%PROJECT_DIR%models\Qwen3-1.7B-Q8_0.gguf"
echo [3/5] Verifica runtime/modello...
if not exist "%LLAMA_EXE%" ( echo       llama-server.exe mancante - necessario download )
if not exist "%MODELLO%"  ( echo       modello Qwen3 1.7B mancante - necessario download )
if not exist "%LLAMA_EXE%" ( set "NEED_DOWNLOAD=1" )
if not exist "%MODELLO%"  ( set "NEED_DOWNLOAD=1" )

if defined NEED_DOWNLOAD (
    REM ------------------------------------------------------------
    REM 4. Download runtime e modello via download_runtime.ps1
    REM ------------------------------------------------------------
    echo [4/5] Download runtime llama.cpp e modello Qwen3.
    echo       Potrebbe impiegare 5-30 minuti (dipende dalla banda).
    echo       Richiesta spazio: ~ 2.5 GB (runtime + modello + cache).
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%scripts\download_runtime.ps1"
    if errorlevel 1 (
        echo.
        echo [ERRORE] Download fallito. Verifica la connessione a Internet.
        echo          Se usi un proxy / VPN, disattivalo temporaneamente.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [4/5] Runtime e modello gia' presenti - salto download.
)

REM ------------------------------------------------------------
REM 5. Self-test veloce e avvio app
REM ------------------------------------------------------------
echo [5/5] Controlli di integrita' e avvio...
set "PYTHONPATH=%PROJECT_DIR%src;%PROJECT_DIR%"
"%VENV_PY%" -m maintenance_ai.main --self-test
if errorlevel 1 (
    echo.
    echo [ATTENZIONE] self-test non superato. Provo comunque ad avviare...
    echo.
)

echo.
echo ============================================================
echo   AVVIO DI MaintenanceAI in corso...
echo ============================================================
echo   Suggerimento: la prima volta il modello impiega ~30 secondi
echo   a venire caricato in RAM.
echo.
"%VENV_PY%" -m maintenance_ai.main
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Applicazione terminata con codice %EXIT_CODE%.
pause
endlocal
exit /b %EXIT_CODE%
