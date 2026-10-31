@echo off
setlocal
cls
echo ==================================================================
echo        MIRAGE 3.0 - AI Execution Assurance Platform
echo   Control AI before it acts. Verify AI after it acts.
echo ==================================================================
echo.
echo Select execution mode:
echo   [1] Core SaaS Engine (Fast - Postgres, Redis, Qdrant, Gateway, Dashboard)
echo   [2] Full Enterprise Cluster (Core + Workers + Grafana + Prometheus)
echo   [3] Run Full Customer Journey Automated Smoke Test
echo   [4] View Live Container Status
echo   [5] Stop All Services (Teardown)
echo.
set /p choice="Enter option [1-5] (Default: 1): "
if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    echo.
    echo Starting Core SaaS Platform...
    docker compose up -d postgres redis qdrant mongodb rabbitmq migration gateway dashboard
    timeout /t 3 /nobreak >nul
    docker compose ps
    echo.
    echo ==================================================================
    echo   MIRAGE Core SaaS Platform is ONLINE!
    echo   - Storefront ^& Dashboard: http://localhost:3000
    echo   - Execution Plane Gateway:  http://localhost:8000
    echo   - OpenAPI Documentation:    http://localhost:8000/docs
    echo   - System Health Status:     http://localhost:8000/v1/health
    echo ==================================================================
    pause
    exit /b 0
)

if "%choice%"=="2" (
    echo.
    echo Starting Full Enterprise Cluster...
    docker compose --profile full up -d
    timeout /t 5 /nobreak >nul
    docker compose ps
    echo.
    echo ==================================================================
    echo   MIRAGE Enterprise Cluster is ONLINE!
    echo   - Storefront ^& Dashboard: http://localhost:3000
    echo   - Execution Plane Gateway:  http://localhost:8000
    echo   - Grafana Monitoring:       http://localhost:3001
    echo   - Prometheus Metrics:       http://localhost:9090
    echo ==================================================================
    pause
    exit /b 0
)

if "%choice%"=="3" (
    echo.
    echo Executing Full Customer Journey Smoke Test...
    python scripts\verify_full_customer_journey.py
    pause
    exit /b 0
)

if "%choice%"=="4" (
    echo.
    docker compose ps
    pause
    exit /b 0
)

if "%choice%"=="5" (
    echo.
    echo Stopping all containers...
    docker compose --profile full down
    echo Done.
    pause
    exit /b 0
)

echo Invalid choice.
pause
