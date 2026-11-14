@echo off
chcp 65001 >nul
title Squad de Ofertas - App

echo ╔═══════════════════════════════════════════════════════════╗
echo ║  Squad de Ofertas - API + Interface                        ║
echo ║  Acesse: https://busca.omnibusca.bid                       ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

rem Verificar chave Groq no .env
set "GROQ_KEY="
for /f "tokens=2 delims==" %%A in ('findstr /R "^OPENAI_API_KEY=" .env 2^>nul') do set "GROQ_KEY=%%A"
set "GROQ_KEY=%GROQ_KEY: =%"

if "%GROQ_KEY%"=="gsk_sua_chave_aqui" (
    echo ⚠️  ATENCAO: Chave Groq NAO configurada!
    echo.
    echo   A IA nao vai funcionar nas buscas.
    echo.
    echo   Para ativar:
    echo   1. Pegue a chave em: https://console.groq.com/keys
    echo   2. Edite .env e substitua: OPENAI_API_KEY=gsk_sua_chave_aqui
    echo   3. Reinicie este script
    echo.
    echo Pressione Enter para continuar SEM IA, ou Ctrl+C para cancelar...
    pause >nul
    echo.
) else if "%GROQ_KEY%"=="" (
    echo ⚠️  ATENCAO: OPENAI_API_KEY nao encontrada no .env
    echo.
    echo Pressione Enter para continuar SEM IA, ou Ctrl+C para cancelar...
    pause >nul
    echo.
) else (
    echo ✅ IA configurada: %GROQ_KEY:~0,12%...
    echo.
)

call iniciar.bat

echo.
echo App parado. Pressione qualquer tecla para fechar...
pause >nul