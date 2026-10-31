# MIRAGE 3.0 One-Click PowerShell Launcher
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  MIRAGE 3.0 - AI Execution Assurance Platform" -ForegroundColor Green
Write-Host "  Starting all services via Docker Compose..." -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

docker compose up -d

Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  MIRAGE 3.0 Services Online!" -ForegroundColor Green
Write-Host "  Frontend Dashboard:  http://localhost:3000" -ForegroundColor White
Write-Host "  FastAPI Gateway:     http://localhost:8000" -ForegroundColor White
Write-Host "  API Documentation:   http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Grafana Monitoring:  http://localhost:3001" -ForegroundColor White
Write-Host "===================================================" -ForegroundColor Cyan
