# start_server.ps1
# Run this to activate the virtual environment and start the Flask server.
# Usage: Right-click → Run with PowerShell  OR  .\start_server.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  IITIIMJobAssistant — Starting server..." -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
$activateScript = Join-Path $PSScriptRoot "venv\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Host "[ERROR] venv not found. Run:  python -m venv venv" -ForegroundColor Red
    exit 1
}
& $activateScript

$runScript = Join-Path $PSScriptRoot "run.py"
python $runScript

