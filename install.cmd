@echo off
rem Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
rem Copyright (C) 2026 Rolf Warnecke - GNU Affero General Public License, Version 3
rem
rem Starter fuer Windows: sucht ein Python ab 3.11 und uebergibt alle
rem Argumente an install.py. Hilfe: install.cmd --help
setlocal
set "HIER=%~dp0"
set "PY="
set "GEFUNDEN="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY call :alt py "py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY call :alt python python
if not defined PY (
    echo Fehler: Python 3.11 oder neuer wurde nicht gefunden. 1>&2
    if defined GEFUNDEN echo   Gefunden: %GEFUNDEN% 1>&2
    echo   Installation: winget install Python.Python.3.13 1>&2
    echo   oder https://www.python.org/downloads/windows/ 1>&2
    set "RC=1"
    goto ende
)
%PY% "%HIER%install.py" %*
set "RC=%errorlevel%"
:ende
rem Per Doppelklick gestartet: Fenster offen halten, damit das Ergebnis lesbar bleibt.
echo %cmdcmdline% | find /i "%~0" >nul
if not errorlevel 1 pause
exit /b %RC%

:alt
rem Remembers an existing but too old interpreter (%1 = program, %2 = command) for the error message.
where %1 >nul 2>&1
if errorlevel 1 exit /b 0
set "V="
for /f "delims=" %%v in ('%~2 --version 2^>^&1') do set "V=%%v"
if not defined V set "V=(Version nicht lesbar)"
if defined GEFUNDEN (set "GEFUNDEN=%GEFUNDEN%; %~2 %V%") else (set "GEFUNDEN=%~2 %V%")
exit /b 0
