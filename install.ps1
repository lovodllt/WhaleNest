$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "请先安装 WSL2、Ubuntu 和 Docker Desktop，见 docs/MANUAL.md" }
$LinuxPath = (& wsl.exe wslpath -u $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法转换 WSL 路径" }
& wsl.exe --cd $LinuxPath bash ./install.sh
if ($LASTEXITCODE -ne 0) { throw "安装未完成，请根据上方错误检查环境" }
