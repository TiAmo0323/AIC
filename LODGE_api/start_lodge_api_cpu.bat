@echo off
setlocal

REM LODGE CPU 兼容启动入口：关闭 CUDA，仅提供 CPU 推理与普通渲染能力。
REM Start LODGE CPU async API.
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

if "%LODGE_PORT%"=="" set "LODGE_PORT=8002"
set "CUDA_VISIBLE_DEVICES=-1"
set "LODGE_CPU_INFER_SCRIPT=infer_lodge_cpu.py"
set "LODGE_CPU_RENDER_SCRIPT=render_cpu.py"

set "LODGE_PYTHON=D:\Anaconda\envs\lodge\python.exe"
if not exist "%LODGE_PYTHON%" (
	set "LODGE_PYTHON=python"
)

echo LODGE_PORT=%LODGE_PORT%
echo CUDA_VISIBLE_DEVICES=%CUDA_VISIBLE_DEVICES%
echo LODGE_CPU_INFER_SCRIPT=%LODGE_CPU_INFER_SCRIPT%
echo LODGE_CPU_RENDER_SCRIPT=%LODGE_CPU_RENDER_SCRIPT%
echo LODGE_PYTHON=%LODGE_PYTHON%
echo.

"%LODGE_PYTHON%" "%~dp0lodge_async_api_cpu.py"

endlocal
