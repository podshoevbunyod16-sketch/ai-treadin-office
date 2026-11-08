# MT5 bridge agent for Windows. Run in PowerShell next to an installed, logged-in MetaTrader 5 terminal.
#   powershell -ExecutionPolicy Bypass -File scripts\start_bridge.ps1 -Port 8765
param(
  [int]$Port = 8765,
  [string]$BindHost = "0.0.0.0",
  [string]$CertFile = "",
  [string]$KeyFile = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
.\.venv\Scripts\pip install -q -r requirements.txt
if (-not $env:ATO_BRIDGE_TOKEN) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $env:ATO_BRIDGE_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
  Write-Host "Generated ATO_BRIDGE_TOKEN (enter it in AI Trading Office -> Accounts):" -ForegroundColor Yellow
  Write-Host $env:ATO_BRIDGE_TOKEN -ForegroundColor Green
}
$pyArgs = @("-m", "app.mt5.bridge_server", "--host", $BindHost, "--port", $Port)
if ($CertFile -and $KeyFile) { $pyArgs += @("--ssl-certfile", $CertFile, "--ssl-keyfile", $KeyFile) }
.\.venv\Scripts\python @pyArgs
