param([string]$Distro = "Ubuntu")
$ErrorActionPreference = "Stop"
$ProjectPath = Split-Path -Parent $PSScriptRoot
$LinuxPath = (& wsl.exe --distribution $Distro wslpath -u $ProjectPath).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法访问指定 WSL 发行版" }
$Arguments = "--distribution `"$Distro`" --cd `"$LinuxPath`" --exec bash ./start.sh"
$Action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName "Dafeiyu" -Action $Action -Trigger $Trigger -Description "Start this Dafeiyu installation at sign-in"
