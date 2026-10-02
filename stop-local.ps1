$ErrorActionPreference = 'Stop'

$repo = [IO.Path]::GetFullPath($PSScriptRoot)
$targets = Get-CimInstance Win32_Process | Where-Object {
    $line = $_.CommandLine
    $line -and (
        ($_.Name -eq 'python.exe' -and $line.Contains($repo) -and
            ($line.Contains('intergen_async_api.py') -or $line.Contains('lodge_async_api.py') -or $line.Contains('motionlint.api:app'))) -or
        ($_.Name -eq 'node.exe' -and $line.Contains($repo) -and $line.Contains('vite.js'))
    )
}

# On Windows the venv launcher may start the base interpreter as a child.
# Its module command line does not include the repository path, so select the
# local 8003 listener only when it is the MotionLint Uvicorn process.
$listener = Get-NetTCPConnection -LocalPort 8003 -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($owner -and $owner.CommandLine -like '*motionlint.api:app*') {
        $targets = @($targets) + @($owner)
    }
}

foreach ($process in ($targets | Sort-Object ProcessId -Unique)) {
    if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $($process.Name) PID $($process.ProcessId)"
    }
}

if (-not $targets) { Write-Host "No HumanAction services from $repo are running." }
