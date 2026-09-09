@echo off
title AI �籨 ��������
echo ==============================================
echo   AI �籨 ��������  http://127.0.0.1:8765
echo   ��������Զ��򿪣��رձ����ڼ�ֹͣ����
echo ==============================================
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" "%PROJECT_DIR%webui.py"
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
