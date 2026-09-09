@echo off
title AI ÿ����Ѷ
echo ==============================================
echo   AI ÿ����Ѷ - �ֶ�����
echo   ÿ���Զ�����������ƻ�������20:00��
echo ==============================================
echo.
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" "%PROJECT_DIR%main.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ���н���������� output Ŀ¼���ɹرձ����ڡ�
pause
exit /b %EXIT_CODE%
