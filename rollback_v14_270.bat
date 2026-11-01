@echo off
setlocal
rem v14.270 rollback helper for extender.py
rem   no arg      -> check only (safe, changes nothing)
rem   rollback    -> restore the pre-v14.270 extender.py
rem   restore     -> re-apply the v14.270 extender.py

set "PY=C:\BSAI\ComfyUI-BSAI_pro_v41\python\python.exe"
set "SCRIPT=%~dp0tools\rollback_v14_270.py"

if not exist "%PY%" (
  echo [ERROR] python not found: %PY%
  goto :end
)
if not exist "%SCRIPT%" (
  echo [ERROR] script not found: %SCRIPT%
  goto :end
)

if "%~1"=="" (
  "%PY%" "%SCRIPT%" check
) else (
  "%PY%" "%SCRIPT%" %~1
)

:end
echo.
pause
endlocal
