$ErrorActionPreference = 'Stop'

$repo = $PSScriptRoot
$runtime = Join-Path (Split-Path $repo -Parent) 'HumanAction-runtime'
$frontend = Join-Path $repo 'project'
$vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'

if (-not (Test-Path -LiteralPath $runtime)) { throw "Runtime directory missing: $runtime" }
if (-not (Test-Path -LiteralPath $vite)) { throw "Frontend dependencies missing: run npm ci in $frontend" }

function Test-LocalUrl([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-LocalUrl([string]$name, [string]$url, [string]$errorLog) {
    for ($i = 0; $i -lt 45; $i++) {
        if (Test-LocalUrl $url) {
            Write-Host "$name ready: $url"
            return
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
    Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', ('"' + $bat + '"')) `
        -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    Wait-LocalUrl $name $url $stderr
}

Start-Api 'InterGen API' 'InterGen_api\start_intergen_api_retarget.bat' 'http://127.0.0.1:8001/health' 'intergen-api'
Start-Api 'LODGE API' 'LODGE_api\start_lodge_api_retarget.bat' 'http://127.0.0.1:8002/health' 'lodge-api'
Start-Api 'MotionLint API' 'motionlint\start_motionlint_api.bat' 'http://127.0.0.1:8003/health' 'motionlint-api'

$frontendUrl = 'http://127.0.0.1:5173/'
if (-not (Test-LocalUrl $frontendUrl)) {
    $node = (Get-Command node -ErrorAction Stop).Source
    $stdout = Join-Path $runtime 'frontend.log'
    $stderr = Join-Path $runtime 'frontend.err.log'
    Start-Process -FilePath $node -ArgumentList @($vite, '--host', '127.0.0.1', '--port', '5173', '--strictPort') `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    Wait-LocalUrl 'Frontend' $frontendUrl $stderr
} else {
    Write-Host "Frontend already running: $frontendUrl"
}

Write-Host 'InterGen, LODGE, MotionLint, Kenney CC0 rendering, and LODGE SMPL-X rendering are configured.'
Write-Host 'Select SMPL for LODGE human mesh, or the open-source cartoon character for InterGen and LODGE.'
