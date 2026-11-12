@echo off
setlocal
set "amy_python=%~dp0.venv\Scripts\python.exe"
if not exist "%amy_python%" (
    echo Set up the Windows Python environment using docs\WINDOWS.md.
    pause
    exit /b 1
)
"%amy_python%" -X utf8 "%~dp0mitan_jarvis.py" %*
set "amy_result=%ERRORLEVEL%"
if not "%amy_result%"=="0" pause
exit /b %amy_result%
