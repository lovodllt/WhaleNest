# Windows 部署与现场反馈

推荐使用 **Docker Desktop＋WSL2 Ubuntu**：微信、桥接、DSH 和语音所需的 Linux 依赖按既有路线运行。`install.ps1` 继续安装到 WSL，原生 Windows 测试入口与它分开，不能混用同一个 `.venv`。

## 推荐入口：WSL2

在项目目录的 PowerShell 中执行：

```powershell
.\install.ps1 -Distro Ubuntu
.\run.ps1 -Action check -Distro Ubuntu
.\run.ps1 -Action start -Distro Ubuntu
.\run.ps1 -Action stop -Distro Ubuntu
```

不需要 Git 也可从 GitHub 下载源码 ZIP。DSH、Node 和 Python 依赖在 Ubuntu 内安装；不要把 Windows 的 Python 或 `node_modules` 直接混进 WSL 环境。

## 原生 Windows 测试入口

这次补齐了跨平台的启停、互斥锁、进程身份核对、UTF-8、时区依赖和 npm 启动入口。**它仍是测试路线，不代表完整微信多媒体链路已在 Windows 验收。** 微信本体继续是 Docker 内的 Linux 微信，不是桌面 Windows 微信。

先安装完整的 Python 3.12、Node.js 24、本机 DSH 和 Docker Desktop。确认从准备运行程序的同一账号执行 `docker info` 成功，并切换到 Linux 容器。Python 不要选缺少 `venv/ensurepip` 的精简或嵌入式发行版。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r config/requirements.txt
.\run-native.ps1 -Action setup
.\run-native.ps1 -Action plugins
.\.venv\Scripts\python.exe -X utf8 scripts/manage.py wechat-package
.\run-native.ps1 -Action build
.\run-native.ps1 -Action start
```

登录及主人绑定沿用快速开始的步骤，将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe -X utf8`。启动器也接受 DSH 的 JavaScript 入口；标准 npm 生成的 `dsh.cmd` 会解析到对应入口，通过 Node 执行。

停止、检查或只开控制台：

```powershell
.\run-native.ps1 -Action check
.\run-native.ps1 -Action stop
.\run-native.ps1 -Action start -ConsoleOnly
```

普通文字发送在 Windows 主机上走 Webox 本机 HTTP 接口，由容器内执行界面操作，避免为每条回复调用宿主 `docker exec`。原生 Windows 的语音转写仍缺少本项目 Linux SQLCipher 路线的完整适配；语音发送、唱歌与部分界面助手也仍需 Docker 执行权限。需要完整能力时使用 WSL2。

## 对应这次反馈的处理

| 反馈 | 处理 |
| --- | --- |
| `getuid` 不存在 | Windows 容器 UID 使用1000，控制台不创建 Linux 的 DBus 环境变量 |
| `kill(pid,0)` 探活误杀 | 删除此探活方式，使用进程查询；服务身份记录包含 PID、创建时间、程序路径与项目脚本 |
| `/proc` 不存在、旧 PID 被复用 | 不依赖 `/proc`；是否运行以实际持有的锁判断，未确认身份的 PID 不作为强制结束对象 |
| 结束服务 | 写 `data/run/stop.flag`，服务自行退出；超时后仅结束身份核对通过的本项目进程树 |
| Windows 后台进程 | 使用 Windows 进程组及分离标志；Linux 保留原有会话方式 |
| `fcntl` 导入失败 | 宿主互斥锁统一入口，Windows 使用 `msvcrt` 字节锁；容器里的 Linux 助手仍使用 `fcntl` |
| 中文配置 GBK 解码失败 | 文本文件明确用 UTF-8；受管理的 Python 子进程显式加 `-X utf8`；PowerShell 文件保存 UTF-8 BOM |
| 嵌入式 Python 找不到 `chat_tasks` | 入口自行添加应用目录；基础依赖补 Windows `tzdata`。这不等于提供了完整嵌入式 Python 安装包 |
| `ui_templates` 目录644、启动循环失败 | 构建时恢复所有助手目录的755权限，普通文件仍保留原有模式 |
| Docker Hub、Go、Debian 源不可访问 | 增加按项目指定的构建源参数，noVNC 与运行环境使用同一组 Debian 源配置 |
| Docker named pipe 权限不足 | 普通回复改走 HTTP；构建、启动容器和需要 Docker 的其他功能仍需相应权限，代码不会更改系统权限 |
| 重启后要求微信登录 | 停止桥接保留微信容器及数据；容器本身重启后仍可能需要在6860页面确认登录，不承诺自动登录 |
| 4.1.13.26 只找到盐、没有明文密钥 | 已有 WCDB 混淆缓冲区补丁；反馈方确认更新后 `/healthz` 为 `ready:true`，这是容器内构建兼容问题 |

## 已配置机器更新

旧版本升级前先用原来的停止入口退出服务。若旧版停止入口本身失效，在任务管理器核对命令行后结束本项目主控及子服务。旧的整数 PID 记录不会被新版本当作可信进程身份；不要让新旧桥接同时运行。

保留 `data/`、`resources/` 和本机配置，更新源码后，原生测试路线执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r config/requirements.txt
.\run-native.ps1 -Action build
.\run-native.ps1 -Action start
```

WSL 路线在 Ubuntu 内更新基础依赖，再执行 `scripts/manage.py build` 和 `scripts/manage.py start`。模板目录权限修复需要重新构建镜像才能生效；替换微信容器后可能需要再次确认登录，不要删除已有微信数据。

## 安装权限与离线准备

如果 pip 因临时目录不可写失败，可在当前 PowerShell 为这次安装指定项目内临时目录：

```powershell
New-Item -ItemType Directory -Force data\tmp | Out-Null
$env:TEMP = (Resolve-Path data\tmp).Path
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pip install -r config/requirements.txt
```

若仍被终端或安全软件拒绝创建进程，应由设备管理员允许相关程序运行，不能靠换 pip/npm 参数绕过。不会默认对 DSH 使用 `--ignore-scripts`，因为它可能跳过安装所需步骤。

可在另一台可联网的 **Windows x64、Python 3.12** 机器上准备基础 wheels，复制到目标电脑后离线安装：

```powershell
py -3.12 -m pip download --only-binary=:all: -r config/requirements.txt -d wheelhouse
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -r config/requirements.txt
```

这只覆盖基础 Python 依赖，不包含 Python、Node、DSH 插件、Docker 镜像、微信安装包和可选语音模型。当前源码包没有捆绑完整离线运行环境；不能把 Linux 的 `node_modules` 当成 Windows 离线依赖直接复制。嵌入式 Python 的 pip 使用不属于普通安装方式，见 [Python 官方说明](https://docs.python.org/3.12/using/windows.html#the-embeddable-package)。

## 构建源设置

以下参数仅作用于本项目本次构建，不修改 Docker 全局配置，也不自动切换微信版本：

```powershell
$env:DAFEIYU_REGISTRY_MIRROR = "docker.m.daocloud.io"
$env:DAFEIYU_GOPROXY = "https://goproxy.cn"
$env:DAFEIYU_APT_MIRROR = "https://mirrors.aliyun.com/debian"
$env:DAFEIYU_APT_SECURITY_MIRROR = "https://mirrors.aliyun.com/debian-security"
.\run-native.ps1 -Action build
```

这些是可选地址示例，可按本机网络换成自己信任且可用的源。WSL 路线请在 Ubuntu 内设置同名环境变量，再执行 `scripts/manage.py build`。
