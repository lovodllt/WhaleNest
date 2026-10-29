param(
    [ValidateSet("init", "setup", "plugins", "start", "stop", "check", "build", "contacts")]
    [string]$Action = "check",
    [switch]$ConsoleOnly
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $Python)) { throw "请先按 docs/WINDOWS.md 创建 Windows Python 3.12 环境；WSL 环境请用 run.ps1" }
$Arguments = @("-X", "utf8", "scripts/manage.py", $Action)
if ($ConsoleOnly) { $Arguments += "--console-only" }
Push-Location $PSScriptRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "执行未完成，请检查 data/logs 与上方提示" }
} finally { Pop-Location }
