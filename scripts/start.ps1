# AI Trading Office - Windows launcher.
# Installs dependencies (including the official MetaTrader5 package), builds the web UI and starts the server.
#   start.bat                      -> http://127.0.0.1:8000 (only this computer)
#   start.bat -BindHost 0.0.0.0    -> accessible from the local network
#   start.bat -Rebuild             -> rebuild the web UI
param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8000,
  [switch]$Rebuild,
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

function Fail($msg) { Write-Host "ОШИБКА: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- Python 64-bit (the MetaTrader5 package exists only for Windows x64)
Step "Проверка Python"
$py = $null
$probe = "import struct,sys;print(struct.calcsize('P')*8,sys.version_info[0],sys.version_info[1])"
foreach ($cand in @(@{ exe = "py"; pre = @("-3-64") }, @{ exe = "py"; pre = @("-3") }, @{ exe = "python"; pre = @() })) {
  if (-not (Get-Command $cand.exe -ErrorAction SilentlyContinue)) { continue }
  try {
    $bits = & $cand.exe @($cand.pre + @("-c", $probe)) 2>$null
    if ($LASTEXITCODE -eq 0 -and $bits) { $py = $cand; break }
  } catch {}
}
if (-not $py) { Fail "Python 3.10+ не найден. Установите 64-битный Python с https://www.python.org/downloads/windows/ (галочка 'Add to PATH')." }
$parts = "$bits".Trim().Split(" ")
if ($parts[0] -ne "64") { Fail "Нужен 64-битный Python (сейчас $($parts[0])-битный): пакет MetaTrader5 выпускается только для x64." }
if ([int]$parts[1] -lt 3 -or ([int]$parts[1] -eq 3 -and [int]$parts[2] -lt 10)) { Fail "Нужен Python 3.10 или новее." }
Write-Host "    Python $($parts[1]).$($parts[2]) x64 ($($py.exe))"

# --- virtualenv + dependencies
Set-Location $Backend
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Step "Создание виртуального окружения backend\.venv"
  & $py.exe @($py.pre + @("-m", "venv", ".venv"))
  if ($LASTEXITCODE -ne 0) { Fail "не удалось создать виртуальное окружение" }
}
$vpy = Join-Path $Backend ".venv\Scripts\python.exe"
Step "Установка зависимостей (включая MetaTrader5)"
& $vpy -m pip install -q --upgrade pip
& $vpy -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install завершился с ошибкой" }
& $vpy -c "import MetaTrader5 as m; print('    MetaTrader5', m.__version__)"
if ($LASTEXITCODE -ne 0) { Fail "пакет MetaTrader5 не импортируется" }

# --- web UI
$dist = Join-Path $Frontend "dist\index.html"
if ($Rebuild -or -not (Test-Path $dist)) {
  Step "Сборка веб-интерфейса"
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "Node.js не найден. Установите LTS-версию с https://nodejs.org и запустите start.bat снова."
  }
  Set-Location $Frontend
  & npm ci --no-audit --no-fund
  if ($LASTEXITCODE -ne 0) { Fail "npm ci завершился с ошибкой" }
  & npm run build
  if ($LASTEXITCODE -ne 0) { Fail "сборка интерфейса завершилась с ошибкой" }
  Set-Location $Backend
}

# --- start
$url = "http://127.0.0.1:$Port"
Step "Запуск AI Trading Office: $url  (Ctrl+C - остановка)"
Write-Host "    Перед торговлей: запустите MetaTrader 5, войдите в демосчёт и включите кнопку 'Алго-трейдинг'." -ForegroundColor Yellow
if (-not $NoBrowser) { Start-Job -ScriptBlock { param($u) Start-Sleep 4; Start-Process $u } -ArgumentList $url | Out-Null }
& $vpy -m uvicorn app.main:app --host $BindHost --port $Port
