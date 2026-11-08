@echo off
rem AI Trading Office - запуск на Windows (рядом с терминалом MetaTrader 5)
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
pause
