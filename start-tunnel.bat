@echo off
chcp 65001 >nul
title Cloudflare Tunnel - Squad de Ofertas

echo ╔═══════════════════════════════════════════════════════════╗
echo ║  Cloudflare Tunnel → https://busca.omnibusca.bid           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
echo Mantenha esta janela ABERTA enquanto usa o app.
echo.
cloudflared tunnel run squad-ofertas

echo.
echo Tunnel parado. Pressione qualquer tecla para fechar...
pause >nul