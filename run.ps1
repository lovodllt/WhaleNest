param(
    [ValidateSet("start", "stop", "check", "build", "contacts")]
    [string]$Action = "start",
    [string]$Distro = "Ubuntu",
    [switch]$ConsoleOnly
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "请先安装 WSL2，见 docs/MANUAL.md" }
$LinuxPath = (& wsl.exe --distribution $Distro --exec wslpath -u $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法访问指定的 WSL 发行版" }
$Arguments = @("scripts/manage.py", $Action)
if ($ConsoleOnly) { $Arguments += "--console-only" }
& wsl.exe --distribution $Distro --cd $LinuxPath --exec .venv/bin/python @Arguments
if ($LASTEXITCODE -ne 0) { throw "执行未完成，请检查上方提示" }
