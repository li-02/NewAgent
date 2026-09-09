@echo off
setlocal
rem AI daily news - scheduled task entry. Output goes to logs\run.log
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== run start %date% %time% ===== >> "%~dp0logs\run.log"
echo [info] working directory: %cd% >> "%~dp0logs\run.log"
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
echo [info] python: %PYTHON_EXE% >> "%~dp0logs\run.log"
"%PYTHON_EXE%" "%PROJECT_DIR%main.py" >> "%~dp0logs\run.log" 2>&1
set "EXIT_CODE=%errorlevel%"
echo ===== run end %date% %time% exit code %EXIT_CODE% ===== >> "%~dp0logs\run.log"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('AI每日资讯定时任务已完成。退出码：%EXIT_CODE%','AI每日资讯')" >> "%~dp0logs\run.log" 2>&1
echo [info] notification exit code %errorlevel% >> "%~dp0logs\run.log"
exit /b %EXIT_CODE%
