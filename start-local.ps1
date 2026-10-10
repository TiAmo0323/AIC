param([switch]$CoreOnly)

$ErrorActionPreference = 'Stop'

$repo = $PSScriptRoot
$runtime = Join-Path $repo 'logs'
$frontend = Join-Path $repo 'project'
$vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'

New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (-not (Test-Path -LiteralPath $vite)) { throw "Frontend dependencies missing: run npm ci in $frontend" }

function Test-LocalUrl([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-LocalUrl([string]$name, [string]$url, [string]$errorLog, [System.Diagnostics.Process]$process) {
    for ($i = 0; $i -lt 300; $i++) {
        if (Test-LocalUrl $url) {
            Write-Host "$name ready: $url"
            return
        }
        if ($process -and $process.HasExited) {
            throw "$name exited before becoming ready. Check $errorLog"
        }
        Start-Sleep -Seconds 1
    }
    throw "$name did not start. Check $errorLog"
}

function Start-Api([string]$name, [string]$relativeBat, [string]$url, [string]$logPrefix) {
    if (Test-LocalUrl $url) {
        Write-Host "$name already running: $url"
        return
    }
    $bat = Join-Path $repo $relativeBat
    $stdout = Join-Path $runtime "$logPrefix.log"
    $stderr = Join-Path $runtime "$logPrefix.err.log"
    $process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', ('"' + $bat + '"')) `
        -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Wait-LocalUrl $name $url $stderr $process
}

if (-not $CoreOnly) {
    & (Join-Path $repo 'scripts\check_runtime_resources.bat')
    Start-Api 'InterGen API' 'InterGen_api\start_intergen_api_retarget.bat' 'http://127.0.0.1:8001/health' 'intergen-api'
    Start-Api 'LODGE API' 'LODGE_api\start_lodge_api_retarget.bat' 'http://127.0.0.1:8002/health' 'lodge-api'
}
Start-Api 'MotionLint API' 'motionlint\start_motionlint_api.bat' 'http://127.0.0.1:8003/health' 'motionlint-api'

$frontendUrl = 'http://127.0.0.1:5173/'
if (-not (Test-LocalUrl $frontendUrl)) {
    $node = (Get-Command node -ErrorAction Stop).Source
    $stdout = Join-Path $runtime 'frontend.log'
    $stderr = Join-Path $runtime 'frontend.err.log'
    $process = Start-Process -FilePath $node -ArgumentList @(('"' + $vite + '"'), '--host', '127.0.0.1', '--port', '5173', '--strictPort') `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Wait-LocalUrl 'Frontend' $frontendUrl $stderr $process
} else {
    Write-Host "Frontend already running: $frontendUrl"
}

Write-Host 'Open http://127.0.0.1:5173/ . Logs are in the logs directory.'
Write-Host 'Service health does not verify generation or rendering; available characters depend on local assets.'
