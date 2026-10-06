@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "LAUNCHER=%PROJECT_ROOT%start_workspace.ps1"
if not exist "%LAUNCHER%" (
  echo Workspace launcher not found.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
if errorlevel 1 (
  echo Workspace launch failed.
  pause
  exit /b 1
)
endlocal
