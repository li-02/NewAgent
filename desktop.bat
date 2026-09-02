@echo off
setlocal
cd /d "%~dp0"
set "APP_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
set "APP_SCRIPT=%~dp0desktop.py"
set "APP_LOG=%~dp0logs\desktop-startup.log"

if not exist "%APP_PYTHON%" goto missing_python
if not exist "%~dp0logs" mkdir "%~dp0logs"

start "AI Daily Desktop" /D "%~dp0" "%APP_PYTHON%" "%APP_SCRIPT%" 2>"%APP_LOG%"
exit /b 0

:missing_python
echo Python virtual environment was not found:
echo %APP_PYTHON%
echo.
echo Run: python -m venv .venv
echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
