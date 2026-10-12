param(
    [string]$PythonPath = '',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = Join-Path (Split-Path -Parent $projectRoot) 'HumanAction-runtime'
if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $projectRoot '.venv\Scripts\python.exe'),
        (Join-Path $runtimeRoot 'envs\motionlint\Scripts\python.exe'),
        (Join-Path $runtimeRoot 'envs\aic-review311\Scripts\python.exe')
    )
    $PythonPath = $candidates | Where-Object {Test-Path -LiteralPath $_ -PathType Leaf} | Select-Object -First 1
    if (-not $PythonPath) {$PythonPath = (Get-Command python -ErrorAction Stop).Source}
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$nodePath = (Get-Command node -ErrorAction Stop).Source
$vitePath = Join-Path $projectRoot 'project\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $vitePath)) {
    throw 'Missing frontend dependencies. Run npm ci in project first.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $PythonPath -c 'import motionlint.api, uvicorn'
    if ($LASTEXITCODE -ne 0) {throw 'Install the current repository with python -m pip install ".[web,render]" first.'}
} finally {Pop-Location}

$logRoot = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$started = @()
foreach ($service in @(
    @{Port=8003; Name='motionlint-api'; Exe=$PythonPath; Args='-m uvicorn motionlint.api:app --host 127.0.0.1 --port 8003'; Dir=$projectRoot},
    @{Port=5173; Name='motionlint-web'; Exe=$nodePath; Args=('"{0}" --host 127.0.0.1 --port 5173 --strictPort' -f $vitePath); Dir=(Join-Path $projectRoot 'project')}
)) {
    if (Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host ("Port {0} already has a service; leaving that process running." -f $service.Port)
        continue
    }
    $process = Start-Process -FilePath $service.Exe -ArgumentList $service.Args -WorkingDirectory $service.Dir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot ($service.Name + '.out.log')) -RedirectStandardError (Join-Path $logRoot ($service.Name + '.err.log'))
    $started += @{name=$service.Name; pid=$process.Id; port=$service.Port}
}
if ($started.Count) {$started | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'motionlint-processes.json') -Encoding UTF8}
Write-Host 'MotionLint: http://127.0.0.1:5173/  API: http://127.0.0.1:8003/health'
if (-not $NoBrowser) {Start-Process 'http://127.0.0.1:5173/'}
