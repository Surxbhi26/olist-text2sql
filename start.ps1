# Start everything for the Olist text-to-SQL demo.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1. Docker + Postgres
Step "Starting Postgres (Docker container olist-pg)"
try { docker info *> $null } catch {
    Write-Host "Docker is not running. Open Docker Desktop, wait for 'Engine running', then rerun this script." -ForegroundColor Red
    exit 1
}
docker start olist-pg | Out-Null
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    docker exec olist-pg pg_isready -U postgres *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { Write-Host "Postgres did not become ready in 30s." -ForegroundColor Red; exit 1 }
Write-Host "Postgres is ready." -ForegroundColor Green

# 2. Ollama
Step "Checking Ollama"
try {
    Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 3 | Out-Null
    Write-Host "Ollama is running." -ForegroundColor Green
} catch {
    Write-Host "Ollama not responding; starting it..." -ForegroundColor Yellow
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 3. Free port 8000 if an old API is still running
$old = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($old) {
    Step "Stopping old process on port 8000"
    $old | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

# 4. API and UI, each in its own window
$activate = ". '$root\venv\Scripts\Activate.ps1'"
Step "Starting the API on http://localhost:8000 (docs: /docs)"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    "Set-Location '$root'; $activate; `$host.UI.RawUI.WindowTitle = 'Olist API'; uvicorn api.main:app --port 8000 --reload"

for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod http://localhost:8000/health -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
}

Step "Starting the Streamlit UI on http://localhost:8501"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    "Set-Location '$root'; $activate; `$host.UI.RawUI.WindowTitle = 'Olist UI'; streamlit run app/streamlit_app.py"

Write-Host "`nAll started. The browser should open at http://localhost:8501" -ForegroundColor Green
Write-Host "To stop: close the 'Olist API' and 'Olist UI' windows (or press Ctrl+C in them)."