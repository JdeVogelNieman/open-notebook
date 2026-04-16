# Start all Open Notebook services
# Usage: .\start.ps1

Write-Host "Starting shared services (Ollama + Speaches)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Failed to start shared services" -ForegroundColor Red; exit 1 }

Write-Host "Starting User 1..." -ForegroundColor Cyan
docker compose -f docker-compose.user1.yml up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Failed to start user 1" -ForegroundColor Red; exit 1 }

Write-Host "Starting User 2..." -ForegroundColor Cyan
docker compose -f docker-compose.user2.yml up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Failed to start user 2" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Health checks
$services = @(
    @{ Name = "User 1"; Url = "http://localhost:5055/api/auth/status" },
    @{ Name = "User 2"; Url = "http://localhost:5056/api/auth/status" }
)

foreach ($svc in $services) {
    try {
        $response = Invoke-WebRequest -Uri $svc.Url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        Write-Host "  $($svc.Name): OK" -ForegroundColor Green
    } catch {
        Write-Host "  $($svc.Name): Not ready yet (may still be starting up)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "All services running!" -ForegroundColor Green
Write-Host "  User 1 frontend: http://localhost:8502"
Write-Host "  User 2 frontend: http://localhost:8503"
