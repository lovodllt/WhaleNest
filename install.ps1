param([string]$Distro = "Ubuntu")
$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "请先安装 WSL2、Ubuntu 和 Docker Desktop，见 docs/MANUAL.md" }
$LinuxPath = (& wsl.exe --distribution $Distro --exec wslpath -u $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法转换 WSL 路径" }
& wsl.exe --distribution $Distro --cd $LinuxPath --exec bash ./install.sh
if ($LASTEXITCODE -ne 0) { throw "安装未完成，请根据上方错误检查环境" }
