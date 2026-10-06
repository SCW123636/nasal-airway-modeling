$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = 'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe'
$server = Join-Path $projectRoot 'work\lib\serve_cfd_workspace.py'
$url = 'http://127.0.0.1:8769/workspace/index.html'
try {
  $health = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8769/health.json' -TimeoutSec 2
  if ($health.StatusCode -eq 200 -and $health.Content -match 'nasal-cfd-local-workspace') {
    Start-Process $url
    exit 0
  }
} catch {}
Start-Process -FilePath $python -ArgumentList @('-X','utf8',$server,'--port','8769','--open') -WorkingDirectory $projectRoot -WindowStyle Hidden
