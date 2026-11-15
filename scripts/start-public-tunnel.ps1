# ==============================================================================
# MIRAGE 3.0: Instant Public Demonstration Tunnel Launcher
# Exposes http://127.0.0.1:3000 to a free, secure Cloudflare HTTPS URL
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  MIRAGE 3.0: Instant Public Demonstration Tunnel        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check if Docker stack is running
$running = docker ps -q --filter "name=mirage-dashboard"
if (-not $running) {
    Write-Host "[1/2] Starting MIRAGE Docker Stack..." -ForegroundColor Yellow
    docker-compose up -d
} else {
    Write-Host "[1/2] MIRAGE Docker Stack is active & healthy." -ForegroundColor Green
}

# 2. Launch Cloudflare Tunnel
Write-Host "[2/2] Launching Cloudflare HTTPS Public Tunnel..." -ForegroundColor Green
Write-Host "Your live public URL will appear below (look for 'https://....trycloudflare.com'):" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop the tunnel at any time.`n" -ForegroundColor DarkGray

.\cloudflared.exe tunnel --url http://127.0.0.1:3000
