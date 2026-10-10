@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
if exist "%PROJECT_ROOT%\config\runtime.local.bat" call "%PROJECT_ROOT%\config\runtime.local.bat"
set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"
pushd "%PROJECT_ROOT%"
"%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 -m shared.runtime_checks --backend intergen
"%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 -m shared.runtime_checks --backend lodge
popd
exit /b 0
