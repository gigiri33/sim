<#
.SYNOPSIS
    Builds iran.zip for offline deployment to Iran servers.

USAGE
    .\build_iran_zip.ps1

BEFORE RUNNING
    1. Download the Xray binary (Linux x86_64):
       https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
    2. Extract the file named "xray" (no extension) from that zip.
    3. Place it at:  iran\xray\xray
    4. Then run this script.
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$IranDir   = Join-Path $ScriptDir "iran"
$XrayBin   = Join-Path $IranDir "xray\xray"
$OutZip    = Join-Path $ScriptDir "iran.zip"

# ── Check xray binary ──────────────────────────────────────────────────────────
if (-not (Test-Path $XrayBin)) {
    Write-Host ""
    Write-Host "  ERROR: xray binary not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  1. Download:" -ForegroundColor Yellow
    Write-Host "     https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    Write-Host ""
    Write-Host "  2. Extract the file named 'xray' (no extension, Linux binary)"
    Write-Host ""
    Write-Host "  3. Place it at:  iran\xray\xray"
    Write-Host ""
    Write-Host "  Then re-run this script." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "  [1/2] xray binary found." -ForegroundColor Green

# ── Build zip ──────────────────────────────────────────────────────────────────
if (Test-Path $OutZip) { Remove-Item $OutZip -Force }

Write-Host "  [2/2] Building iran.zip ..." -ForegroundColor Cyan

Compress-Archive -Path $IranDir -DestinationPath $OutZip

$sizeMB = [math]::Round((Get-Item $OutZip).Length / 1MB, 1)

Write-Host ""
Write-Host "  Done!  iran.zip  ($sizeMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  STEP 1 — Transfer to Iran server:" -ForegroundColor White
Write-Host "    scp iran.zip root@YOUR_IRAN_SERVER_IP:/tmp/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  STEP 2 — Install on the server (no internet needed):" -ForegroundColor White
Write-Host "    ssh root@YOUR_IRAN_SERVER_IP" -ForegroundColor Cyan
Write-Host "    cd /tmp && unzip iran.zip && cd iran && chmod +x install.sh && sudo ./install.sh" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
