@echo off
title MIRAGE 3.0 - Public Demonstration Tunnel
echo ==========================================================
echo   MIRAGE 3.0: Instant Public Demonstration Tunnel
echo ==========================================================
powershell -ExecutionPolicy Bypass -File "%~dp0start-public-tunnel.ps1"
pause
