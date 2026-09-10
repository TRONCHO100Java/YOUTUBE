<#
.SYNOPSIS
    Levanta el entorno de desarrollo completo de ClipForge.
.DESCRIPTION
    Arranca Docker Desktop si hace falta, levanta PostgreSQL y Redis, aplica las
    migraciones pendientes, abre la API, el worker Celery y el frontend en
    ventanas separadas y termina abriendo el navegador.
    Para lanzarlo con doble clic usa ClipForge.bat.
.EXAMPLE
    .\start-dev.ps1
#>
[CmdletBinding()]
param(
    # No abrir el frontend (util si solo trabajas en el backend).
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

# Sondea un ejecutable externo y devuelve $true si su codigo de salida es 0.
# En PowerShell 5.1 redirigir stderr de un .exe genera un NativeCommandError que,
# con $ErrorActionPreference = 'Stop', aborta el script. Por eso bajamos la
# preferencia a 'Continue' mientras dura la llamada.
function Test-Command([scriptblock]$Command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

Assert-Path $venvPython 'Crea el entorno: py -3.12 -m venv apps\backend\.venv'
Assert-Path (Join-Path $root '.env') 'Copia la configuracion: Copy-Item .env.example .env'

if (-not (Test-Command { docker info })) {
    $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    Assert-Path $dockerDesktop 'Instala Docker Desktop: https://www.docker.com/products/docker-desktop/'
    Write-Host '==> Arrancando Docker Desktop (puede tardar un par de minutos)...' -ForegroundColor Cyan
    Start-Process $dockerDesktop
    $dockerReady = $false
    foreach ($attempt in 1..150) {
        Start-Sleep -Seconds 2
        if (Test-Command { docker info }) { $dockerReady = $true; break }
    }
    if (-not $dockerReady) { throw 'Docker Desktop no responde tras 5 minutos.' }
}

Write-Host '==> Levantando PostgreSQL y Redis...' -ForegroundColor Cyan
docker compose --project-directory $root up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose ha fallado.' }

Write-Host '==> Esperando a que PostgreSQL acepte conexiones...' -ForegroundColor Cyan
$ready = $false
foreach ($attempt in 1..30) {
    if (Test-Command { docker exec clipforge-postgres pg_isready -U clipforge -d clipforge }) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'PostgreSQL no responde tras 30 segundos.' }

Write-Host '==> Aplicando migraciones...' -ForegroundColor Cyan
# Desde apps\backend y no con -c: el script_location del alembic.ini es
# relativo, asi que apuntarle el fichero desde otro directorio no basta.
Push-Location $backend
try {
    & '.\.venv\Scripts\alembic.exe' upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Las migraciones han fallado.' }
} finally {
    Pop-Location
}

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

Write-Host '==> Abriendo temporizador (Celery beat)...' -ForegroundColor Cyan
# Proceso aparte y no '-B' dentro del worker: el beat embebido no funciona
# en Windows, Celery lo rechaza al arrancar. Es quien dispara la revision
# de los canales vigilados; sin el, los videos nuevos solo entran a mano.
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$backend'; .\.venv\Scripts\celery.exe -A clipforge.worker.celery_app beat --loglevel=info"
)

if (-not $NoWeb) {
    Write-Host '==> Abriendo frontend (puerto 3000)...' -ForegroundColor Cyan
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command', "Set-Location '$web'; npm run dev"
    )

    Write-Host '==> Esperando al frontend para abrir el navegador...' -ForegroundColor Cyan
    foreach ($attempt in 1..90) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:3000' -TimeoutSec 2 | Out-Null
            Start-Process 'http://localhost:3000'
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host ''
Write-Host 'ClipForge en marcha:' -ForegroundColor Green
Write-Host '  Frontend  http://localhost:3000'
Write-Host '  API       http://localhost:8000'
Write-Host '  OpenAPI   http://localhost:8000/docs'
Write-Host ''
Write-Host 'Cierra las cuatro ventanas de PowerShell para parar la aplicacion.'
