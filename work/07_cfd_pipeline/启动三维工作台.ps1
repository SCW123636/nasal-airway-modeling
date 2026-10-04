$ErrorActionPreference = 'Stop'
$taskPython = 'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe'
$taskWork = Split-Path -Parent $PSScriptRoot
$taskServer = Join-Path $taskWork 'lib\serve_cfd_workspace.py'
Start-Process -FilePath $taskPython -ArgumentList @('-X','utf8',$taskServer,'--port','8769','--open') -WindowStyle Hidden
