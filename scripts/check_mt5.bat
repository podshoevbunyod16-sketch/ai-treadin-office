@echo off
rem Проверка подключения к MetaTrader 5 тем же кодом, что использует веб-приложение.
rem   scripts\check_mt5.bat                      - подключиться к уже авторизованному терминалу
rem   scripts\check_mt5.bat --trade              - плюс тестовая сделка минимальным лотом (только DEMO)
rem   scripts\check_mt5.bat --login 5012345 --server MetaQuotes-Demo --symbol EURUSD
chcp 65001 >nul
cd /d "%~dp0..\backend"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала запустите start.bat - он установит зависимости.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m app.mt5.diagnose %*
pause
