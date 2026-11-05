<# 
.SYNOPSIS
    Add, commit e push automático com mensagem única.

.DESCRIPTION
    Verifica se há mudanças, faz git add -A, commit com a mensagem informada
    e git push. Útil para commits rápidos durante desenvolvimento.

.PARAMETER Message
    Mensagem do commit (obrigatória).

.PARAMETER NoVerify
    Pula hooks de pre-commit (útil se hooks estiverem lentos ou quebrados).

.EXAMPLE
    .\git-auto-commit.ps1 "feat: adicionar filtro por categoria"

.EXAMPLE
    .\git-auto-commit.ps1 "fix: corrigir bug no cache" -NoVerify

.NOTES
    Coloque este arquivo na raiz do repositório (junto ao .git).
    Requer Git instalado e configurado (user.name, user.email).
#>

param(
    [Parameter(Mandatory=$true, Position=0)][string]$Message,
    [switch]$NoVerify
)

# Verifica se estamos em um repo git
if (-not (Test-Path ".git")) {
    Write-Error "❌ Não é um repositório git. Rode na raiz do projeto."
    exit 1
}

# Verifica se há mudanças
$changes = git status --porcelain
if (-not $changes) {
    Write-Host "📭 Nada para commitar (working tree clean)." -ForegroundColor Yellow
    exit 0
}

# Mostra resumo das mudanças
Write-Host "📝 Alterações detectadas:" -ForegroundColor Cyan
git status --short
Write-Host ""

# Git add
Write-Host "➕ Adicionando arquivos..." -ForegroundColor Cyan
git add -A

# Git commit
$commitCmd = "git commit"
if ($NoVerify) { $commitCmd += " --no-verify" }
$commitCmd += " -m `"$Message`""
Write-Host "💾 Commitando: $Message" -ForegroundColor Cyan
Invoke-Expression $commitCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Falha no commit."
    exit $LASTEXITCODE
}

# Git push
Write-Host "🚀 Enviando para o remote..." -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Falha no push. Verifique credenciais/permissões."
    exit $LASTEXITCODE
}

Write-Host "✅ Commit e push concluídos com sucesso!" -ForegroundColor Green