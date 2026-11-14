@echo off
chcp 65001 >nul
title Parando Squad de Ofertas

echo Parando serviços...

taskkill /f /im cloudflared.exe >nul 2>&1 && echo ✅ Cloudflare Tunnel parado

rem Fecha apenas os navegadores ocultos usados por scraping (mantem seu Edge normal)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like '*browser_profile*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

taskkill /f /im python.exe >nul 2>&1 && echo ✅ App Python parado
taskkill /f /im uvicorn.exe >nul 2>&1

echo.
echo Tudo parado. Pressione qualquer tecla...
pause >nul