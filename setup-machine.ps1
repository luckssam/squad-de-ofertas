<# 
.SYNOPSIS
    Configura o ambiente do Squad de Ofertas em uma nova máquina Windows.

.DESCRIPTION
    - Clona o repositório (se não existir)
    - Cria virtualenv Python
    - Instala dependências
    - Copia .env.example para .env
    - Abre .env no editor para configurar chaves
    - Opcionalmente roda o app

.PARAMETER RepoUrl
    URL do repositório GitHub (padrão: luckssmau/squad-de-ofertas)

.PARAMETER TargetDir
    Diretório onde clonar/criar o projeto (padrão: pasta atual\squad-de-ofertas)

.PARAMETER RunAfterSetup
    Se true, inicia o app automaticamente após configurar.

.PARAMETER Editor
    Editor para abrir o .env (padrão: notepad). Use 'code' para VS Code, 'notepad++', etc.

.EXAMPLE
    .\setup-machine.ps1

.EXAMPLE
    .\setup-machine.ps1 -RunAfterSetup

.EXAMPLE
    .\setup-machine.ps1 -TargetDir "D:\projetos\squad" -Editor code

.NOTES
    Requer: Git, Python 3.11+ instalados e no PATH.
    Rode no PowerShell como Administrador se der erro de permissão.
#>

param(
    [string]$RepoUrl = "https://github.com/luckssmau/squad-de-ofertas.git",
    [string]$TargetDir = ".\squad-de-ofertas",
    [switch]$RunAfterSetup,
    [string]$Editor = "notepad"
)

# ---- Helpers ----
function Write-Step { param([string]$msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "✅ $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "⚠️  $msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$msg) Write-Host "❌ $msg" -ForegroundColor Red }

function Check-Command {
    param([string]$cmd, [string]$name)
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Err "$name não encontrado no PATH. Instale e tente novamente."
        exit 1
    }
    Write-Ok "$name encontrado: $((& $cmd --version 2>&1 | Select-Object -First 1))"
}

# ---- Início ----
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Squad de Ofertas — Setup de nova máquina                  ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

# 1. Verificar pré-requisitos
Write-Step "Verificando pré-requisitos"
Check-Command "git" "Git"
Check-Command "python" "Python"
Check-Command "pip" "pip"

$pyVersion = python --version 2>&1
if ($pyVersion -notmatch '3\.(1[1-9]|[2-9]\d)') {
    Write-Warn "Python $pyVersion detectado. Recomendado 3.11+"
} else {
    Write-Ok "Python $pyVersion OK"
}

# 2. Clonar ou atualizar repo
$targetPath = Resolve-Path $TargetDir -ErrorAction SilentlyContinue
if ($targetPath -and (Test-Path "$targetPath\.git")) {
    Write-Step "Atualizando repositório existente em $targetPath"
    Set-Location $targetPath
    git pull
    Write-Ok "Repositório atualizado"
} else {
    Write-Step "Clonando repositório para $TargetDir"
    $parent = Split-Path $TargetDir -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    git clone $RepoUrl $TargetDir
    if ($LASTEXITCODE -ne 0) { Write-Err "Falha ao clonar"; exit 1 }
    Set-Location $TargetDir
    Write-Ok "Repositório clonado"
}

# 3. Virtualenv
Write-Step "Criando/verificando virtualenv"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Ok "Virtualenv criada em .venv"
} else {
    Write-Ok "Virtualenv já existe"
}

# 4. Instalar dependências
Write-Step "Instalando dependências"
.\.venv\Scripts\python.exe -m pip install --upgrade pip -q
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Err "Falha ao instalar dependências"; exit 1 }
Write-Ok "Dependências instaladas"

# 5. Configurar .env
Write-Step "Configurando .env"
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Ok ".env criado a partir de .env.example"
} else {
    Write-Warn ".env já existe — mantendo o atual"
}

# 6. Abrir .env para edição
Write-Step "Abrindo .env para configurar chaves"
Write-Host "   Preencha pelo menos:" -ForegroundColor Yellow
Write-Host "   • SERPAPI_KEY (obrigatório para buscas reais)" -ForegroundColor Yellow
Write-Host "   • DEMO_MODE=false" -ForegroundColor Yellow
Write-Host "   • MELI_CLIENT_ID / MELI_CLIENT_SECRET (opcional, para Mercado Livre)" -ForegroundColor Yellow
Write-Host "   • OPENAI_API_KEY (opcional, para IA)" -ForegroundColor Yellow
Write-Host ""
Write-Host "   Pressione Enter após salvar e fechar o editor..." -ForegroundColor Cyan
& $Editor .env
Read-Host | Out-Null
Write-Ok ".env salvo"

# 7. Testar saúde da API (opcional)
Write-Step "Testando se o app sobe"
$proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "app.py" -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 4
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Ok "App respondeu: $($health.status) | demo=$($health.demo) | llm=$($health.llm)"
} catch {
    Write-Warn "App não respondeu no healthcheck (pode estar subindo ainda)."
}
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue

# 8. Rodar se solicitado
if ($RunAfterSetup) {
    Write-Step "Iniciando app (Ctrl+C para parar)..."
    Write-Host "   Acesse: http://127.0.0.1:8765" -ForegroundColor Cyan
    .\iniciar.bat
} else {
    Write-Host "`n🎉 Setup concluído!" -ForegroundColor Green
    Write-Host "Para rodar:" -ForegroundColor Cyan
    Write-Host "   .\iniciar.bat" -ForegroundColor Cyan
    Write-Host "   ou" -ForegroundColor Cyan
    Write-Host "   .\git-auto-commit.ps1 `"sua mensagem`"  # após fazer mudanças" -ForegroundColor Cyan
    Write-Host "`nAcesse: http://127.0.0.1:8765" -ForegroundColor Cyan
}