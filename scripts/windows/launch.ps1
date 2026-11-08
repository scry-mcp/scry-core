# Runs on the Windows host, beside the run root: registers scry-<Step> as an interactive task,
# waits for its marker within the bound, unregisters it, and prints its log.
param([string]$Step, [int]$Seconds = 1800)
$W = $PSScriptRoot
$done = Join-Path $W "logs\$Step.done"
Remove-Item -ErrorAction SilentlyContinue $done
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$W\scry-run.cmd`" $Step"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName "scry-$Step" -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "scry-$Step"
$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline -and -not (Test-Path $done)) { Start-Sleep -Seconds 5 }
Unregister-ScheduledTask -TaskName "scry-$Step" -Confirm:$false
if (Test-Path $done) { 'DONE' } else { 'TIMEOUT' }
Get-Content (Join-Path $W "logs\$Step.log")
