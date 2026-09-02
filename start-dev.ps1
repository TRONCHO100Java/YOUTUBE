<#
.SYNOPSIS
    Levanta el entorno de desarrollo completo de ClipForge.
.DESCRIPTION
    Arranca PostgreSQL y Redis con Docker, aplica las migraciones pendientes y
    abre la API, el worker Celery y el frontend en ventanas separadas.
.EXAMPLE
    .\start-dev.ps1
#>
[CmdletBinding()]
param(
    # No abrir el frontend (útil si solo trabajas en el backend).
    [switch]$NoWeb
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'apps\backend'
$web = Join-Path $root 'apps\web'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'

function Assert-Path([string]$Path, [string]$Hint) {
    if (-not (Test-Path $Path)) { throw "No encontrado: $Path`n$Hint" }
}

Assert-Path $venvPython 'Crea el entorno: py -3.12 -m venv apps\backend\.venv'
Assert-Path (Join-Path $root '.env') 'Copia la configuracion: Copy-Item .env.example .env'

Write-Host '==> Levantando PostgreSQL y Redis...' -ForegroundColor Cyan
docker compose --project-directory $root up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose ha fallado. ¿Está Docker Desktop arrancado?' }

Write-Host '==> Esperando a que PostgreSQL acepte conexiones...' -ForegroundColor Cyan
$ready = $false
foreach ($attempt in 1..30) {
    docker exec clipforge-postgres pg_isready -U clipforge -d clipforge *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'PostgreSQL no responde tras 30 segundos.' }

Write-Host '==> Aplicando migraciones...' -ForegroundColor Cyan
& (Join-Path $backend '.venv\Scripts\alembic.exe') -c (Join-Path $backend 'alembic.ini') upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Las migraciones han fallado.' }

Write-Host '==> Abriendo API (puerto 8000)...' -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$backend'; .\.venv\Scripts\uvicorn.exe clipforge.api.main:app --reload --port 8000"
)

Write-Host '==> Abriendo worker Celery...' -ForegroundColor Cyan
# --pool=solo es obligatorio en Windows: el pool prefork de Celery no funciona.
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$backend'; .\.venv\Scripts\celery.exe -A clipforge.worker.celery_app worker --loglevel=info --pool=solo -Q cpu,gpu"
)

if (-not $NoWeb) {
    Write-Host '==> Abriendo frontend (puerto 3000)...' -ForegroundColor Cyan
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command', "Set-Location '$web'; npm run dev"
    )
}

Write-Host ''
Write-Host 'ClipForge en marcha:' -ForegroundColor Green
Write-Host '  Frontend  http://localhost:3000'
Write-Host '  API       http://localhost:8000'
Write-Host '  OpenAPI   http://localhost:8000/docs'
