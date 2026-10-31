# ==============================================================================
# MIRAGE 3.0: One-Click Production & Developer Orchestration Launcher
# ==============================================================================
param (
    [string]$Mode = ""
)

Clear-Host
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "       MIRAGE 3.0 - AI Execution Assurance Platform" -ForegroundColor Green
Write-Host "  Control AI before it acts. Verify AI after it acts." -ForegroundColor Gray
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $Mode) {
    Write-Host "Select execution mode:" -ForegroundColor Yellow
    Write-Host "  [1] Core SaaS Engine (Fast - Postgres, Redis, Qdrant, Gateway, Dashboard)" -ForegroundColor White
    Write-Host "  [2] Full Enterprise Cluster (Core + Workers + Grafana + Prometheus + Tempo)" -ForegroundColor White
    Write-Host "  [3] Run Full Customer Journey Automated Smoke Test" -ForegroundColor White
    Write-Host "  [4] View Live Container Status & Health" -ForegroundColor White
    Write-Host "  [5] Stop All Services (Teardown)" -ForegroundColor White
    Write-Host ""
    $Choice = Read-Host "Enter option [1-5] (Default: 1)"
    if (-not $Choice) { $Choice = "1" }
} else {
    $Choice = $Mode
}

switch ($Choice) {
    { $_ -in "1", "core", "fast" } {
        Write-Host "`n>>> Starting Core SaaS Platform..." -ForegroundColor Cyan
        docker compose up -d postgres redis qdrant mongodb rabbitmq migration gateway dashboard
        Write-Host "`n>>> Waiting for Gateway to report healthy..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
        docker compose ps
        Write-Host "`n==================================================================" -ForegroundColor Green
        Write-Host "  MIRAGE Core SaaS Platform is ONLINE!" -ForegroundColor Green
        Write-Host "  - Storefront & Operator Dashboard: http://localhost:3000" -ForegroundColor White
        Write-Host "  - Execution Plane Gateway:         http://localhost:8000" -ForegroundColor White
        Write-Host "  - Interactive OpenAPI Contracts:   http://localhost:8000/docs" -ForegroundColor White
        Write-Host "  - System Health & Gate Status:     http://localhost:8000/v1/health" -ForegroundColor White
        Write-Host "==================================================================" -ForegroundColor Green
    }
    { $_ -in "2", "full", "enterprise" } {
        Write-Host "`n>>> Starting Full Enterprise Cluster with Observability..." -ForegroundColor Cyan
        docker compose --profile full up -d
        Write-Host "`n>>> Waiting for Services..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        docker compose ps
        Write-Host "`n==================================================================" -ForegroundColor Green
        Write-Host "  MIRAGE Enterprise Cluster is ONLINE!" -ForegroundColor Green
        Write-Host "  - Storefront & Operator Dashboard: http://localhost:3000" -ForegroundColor White
        Write-Host "  - Execution Plane Gateway:         http://localhost:8000" -ForegroundColor White
        Write-Host "  - Grafana Telemetry Dashboards:    http://localhost:3001" -ForegroundColor White
        Write-Host "  - Prometheus Metrics Engine:       http://localhost:9090" -ForegroundColor White
        Write-Host "==================================================================" -ForegroundColor Green
    }
    { $_ -in "3", "test", "verify" } {
        Write-Host "`n>>> Executing Full Customer Journey Smoke Test..." -ForegroundColor Cyan
        python scripts/verify_full_customer_journey.py
    }
    { $_ -in "4", "status", "ps" } {
        Write-Host "`n>>> Checking Container Status..." -ForegroundColor Cyan
        docker compose ps
    }
    { $_ -in "5", "down", "stop" } {
        Write-Host "`n>>> Stopping All Services..." -ForegroundColor Yellow
        docker compose --profile full down
        Write-Host ">>> All MIRAGE containers terminated safely." -ForegroundColor Green
    }
    Default {
        Write-Host "Invalid option. Exiting." -ForegroundColor Red
    }
}
