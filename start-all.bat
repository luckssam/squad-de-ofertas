@echo off
chcp 65001 >nul
title Squad de Ofertas - Iniciando tudo

echo ╔═══════════════════════════════════════════════════════════╗
echo ║  Squad de Ofertas — Iniciando túnel + app                  ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

echo [1/2] Iniciando Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k "cloudflared tunnel run squad-ofertas"

timeout /t 3 /nobreak >nul

echo [2/2] Iniciando App Squad de Ofertas...
cd /d "%~dp0"
call iniciar.bat

echo.
echo Pressione qualquer tecla para fechar todas as janelas...
pause >nul

taskkill /f /im cloudflared.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1