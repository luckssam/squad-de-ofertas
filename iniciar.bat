@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual e instalando dependencias...
  py -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Arquivo .env criado a partir do exemplo.
)

echo.
echo  Squad de Ofertas
echo  Abrindo http://127.0.0.1:8765
echo  Pressione Ctrl+C para encerrar.
echo.

".venv\Scripts\python.exe" app.py
goto :eof

:error
echo.
echo Falha ao iniciar. Verifique se o Python 3.11+ esta instalado (comando: py --version).
pause
