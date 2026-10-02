@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "MOTIONLINT_PYTHON=%PROJECT_ROOT%\..\HumanAction-runtime\envs\motionlint\Scripts\python.exe"
if not exist "%MOTIONLINT_PYTHON%" (
  echo MotionLint environment not found: %MOTIONLINT_PYTHON%
  exit /b 1
)
set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"
pushd "%PROJECT_ROOT%"
"%MOTIONLINT_PYTHON%" -m uvicorn motionlint.api:app --host 127.0.0.1 --port 8003
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
