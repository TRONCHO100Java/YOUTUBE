@echo off
title ClipForge
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
if errorlevel 1 (
    echo.
    echo *** El arranque ha fallado. Revisa el mensaje de arriba. ***
    echo.
    pause
)
