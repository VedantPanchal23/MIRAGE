@echo off
echo ===================================================
echo   MIRAGE 3.0 - AI Execution Assurance Platform
echo   Starting all containers via Docker Compose...
echo ===================================================

docker compose up -d

echo.
echo ===================================================
echo   MIRAGE Services Online!
echo   Frontend Dashboard:  http://localhost:3000
echo   FastAPI Gateway:     http://localhost:8000
echo   API Documentation:   http://localhost:8000/docs
echo   Grafana Monitoring:  http://localhost:3001
echo ===================================================
pause
