$ErrorActionPreference='Stop'
$snapshot=Get-CimInstance Win32_Process
$ids=@($snapshot | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -match 'run_isolated_semantic.py'} | ForEach-Object {$_.ProcessId})
do {
    $new=@($snapshot | Where-Object {$_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids} | ForEach-Object {$_.ProcessId})
    $ids+= $new
} while($new.Count -gt 0)
$before=@{}
foreach($processId in $ids){try {$before[$processId]=(Get-Process -Id $processId).CPU}catch{}}
$at=Get-Date
Start-Sleep -Seconds 3
$elapsed=((Get-Date)-$at).TotalSeconds
$rows=@()
foreach($processId in $before.Keys){
    try {
        $p=Get-Process -Id $processId
        $delta=$p.CPU-$before[$processId]
        $rows+=@{pid=$processId;name=$p.Name;affinity_mask_hex=('{0:X}' -f [long]$p.ProcessorAffinity);cpu_seconds=$delta;working_set_mb=$p.WorkingSet64/1MB}
    }catch{}
}
$r=@{at=(Get-Date).ToString('o');logical_cpu_count=[Environment]::ProcessorCount;duration_s=$elapsed;processes=$rows;tree_cpu_fraction=($rows|Measure-Object -Property cpu_seconds -Sum).Sum/($elapsed*[Environment]::ProcessorCount)}
$line=$r | ConvertTo-Json -Depth 4 -Compress
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'resource_samples.jsonl') -Value $line -Encoding utf8
$r|ConvertTo-Json -Depth 4
