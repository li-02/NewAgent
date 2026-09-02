@echo off
title AI 每日资讯
echo ==============================================
echo   AI 每日资讯 - 手动运行
echo   每天自动运行由任务计划程序负责（20:00）
echo ==============================================
echo.
"E:\documents\zixun\.venv\Scripts\python.exe" "E:\documents\zixun\main.py" %*
echo.
echo 运行结束。稿件在 output 目录，可关闭本窗口。
pause
