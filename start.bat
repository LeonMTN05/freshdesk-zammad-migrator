@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem ---------------------------------------------------------------
rem  Freshdesk -> Zammad Migrator: Setup + Start
rem  Legt beim ersten Aufruf eine virtuelle Umgebung (.venv) an,
rem  installiert die Abhaengigkeiten und startet danach die GUI.
rem ---------------------------------------------------------------

where python >nul 2>nul
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden.
    echo          Bitte Python 3.11 oder neuer installieren: https://www.python.org/downloads/
    echo          Bei der Installation "Add python.exe to PATH" anhaken.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Erstelle virtuelle Umgebung .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import PySide6, requests" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installiere Abhaengigkeiten - das dauert beim ersten Mal einige Minuten ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [FEHLER] Installation fehlgeschlagen - Meldung siehe oben.
        echo          Falls dort ein "Long Path"-Fehler steht: Windows-Unterstuetzung
        echo          fuer lange Pfade aktivieren ^(https://pip.pypa.io/warnings/enable-long-paths^)
        echo          und start.bat erneut ausfuehren.
        pause
        exit /b 1
    )
)

echo [START] Freshdesk -^> Zammad Migrator wird gestartet ...
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [FEHLER] Das Programm wurde mit einem Fehler beendet. Details: migration.log
    pause
)
endlocal
