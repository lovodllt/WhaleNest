# 手动安装、升级和故障处理

## 运行结构

Docker 运行固定版本的 Linux 微信及 Webox；本机虚拟环境运行消息桥接、控制台和可选 TTS，通过本机 DSH 的 stdio SDK 调用模型。这里的 Docker 方案不是将本机 DSH 改成一个公开的模型代理。

程序目录是解压目录；`data/` 是当前使用者的私人运行数据；`resources/` 是人设和设定图片；模型按资源清单放在插件目录或 `resources/models/`。

## Linux 前置依赖

Ubuntu 示例：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git curl
```

从 [Node.js](https://nodejs.org/en/download) 安装 Node.js 24；从 [Docker 官方教程](https://docs.docker.com/engine/install/ubuntu/) 安装 Docker Engine 和 Compose 插件。确认当前用户有使用 Docker 的权限，执行 `docker info` 能正常返回。不要为了运行本项目把 Docker API 暴露到公网。

```bash
npm install -g @deepseek-ai/dsh@0.2.1-rc.2
```

## Windows 前置依赖

使用 [WSL 官方教程](https://learn.microsoft.com/windows/wsl/install) 安装 WSL2 和 Ubuntu，安装 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)，启用目标 Ubuntu 的 WSL 集成。后续依赖、DSH、Python 和本项目的命令均在该 Ubuntu 内执行，与 Linux 步骤一致。

首版不支持无 WSL2 的 Windows 原生 Python 桥接，也未在实体 Windows 设备完成端到端验收。PowerShell 启动器已提供；若路径或发行版设置不同，直接进入 Ubuntu 执行相同命令。

## 分步配置

在解压目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r config/requirements.txt
.venv/bin/python scripts/manage.py setup
.venv/bin/python scripts/manage.py plugins
.venv/bin/python scripts/manage.py check
```

`setup` 创建自己的配置和 DSH 专用 profiles，名字为 `dafeiyu-direct`、`dafeiyu-group`、`dafeiyu-memory`、`dafeiyu-image`、`dafeiyu-runtime`。不会修改已有的 `web` 或其他 profiles；遇到不属于本安装器的同名目录会停止。插件版本固定在对应 package.json，npm 安装后生成本机锁文件。

初始化文件：

| 文件 | 内容 |
| --- | --- |
| `config/runtime.json` | 本机 Node、DSH、模型地址和名称 |
| `config/secrets.json` | 自己的模型服务密钥，不公开 |
| `config/chat.json` | 功能开关、会话规则、歌曲索引 |
| `config/voice.json` | 微软音色、音高、语速和音量 |

模型服务地址由 DSH 使用。例如兼容 OpenAI 的服务通常需要填写服务方提供的完整 base URL；是否需要 `/v1` 以服务方要求为准。识图需要配置具有图片输入能力的模型；程序本身不会让纯文字模型获得视觉能力。

## 微信环境

```bash
.venv/bin/python scripts/manage.py wechat-package
.venv/bin/python scripts/manage.py build
.venv/bin/python scripts/manage.py start
```

固定适配版本为 Linux 微信 `4.1.13.26`、amd64。微信安装包不随发布包提供。下载工具核对 `config/wechat-package.json` 中的 SHA256；如果官方链接已经更新，会停止而不是擅自切换版本。

已有这一版本的官方 deb 可以手动导入：

```bash
.venv/bin/python scripts/manage.py wechat-package --file /自己的路径/WeChatLinux_x86_64.deb
```

然后按 [一键配置教程](QUICKSTART.md#微信登录和主人绑定) 完成微信登录和主人绑定。

本项目端口为 48080（Webox）、6860（微信画面）、8877（控制台）、8878（私有远程入口）、9981（可选微软 TTS）。只绑定本机。启动器自动匹配宿主用户 UID，避免不同电脑的数据权限不一致；若跳过启动器直接执行 `docker compose up`，应自行设置 `DAFEIYU_UID` 为运行桥接的用户 UID。容器名为 `dafeiyu-wechat`，与维护者当前实例分开；同一电脑部署多份时，需要统一修改 compose 和程序对应地址，不支持只改其中一处端口。

## 网络问题

Docker Hub 无法访问时，可以明确选择镜像源重新构建，示例：

```bash
DAFEIYU_REGISTRY_MIRROR=mirror.gcr.io .venv/bin/python scripts/manage.py build
```

该参数只影响这次构建的基础镜像地址，不修改 Docker 全局配置或系统网络。镜像源也可能受当地网络影响。Debian 软件源可通过 Docker 构建参数 `APT_DEBIAN_MIRROR`、`APT_DEBIAN_SECURITY_MIRROR` 指定；保留版本与校验规则。

“没有收到消息”先区分：微信未登录、DSH 模型配置错误、插件缺少、暂停回复、没有匹配唤醒条件。查看控制台状态及 `data/logs/bridge.log`、`data/chat/dsh-diagnostics.log`。不要把微信未登录误判为模型断连，也不要通过重复重建容器处理模型配置问题。

若仅想先配置控制台，不启动微信容器：

```bash
.venv/bin/python scripts/manage.py start --console-only
```

## 自启

Linux 使用用户服务：

```bash
bash stop.sh
.venv/bin/python scripts/autostart.py
systemctl --user start dafeiyu.service
```

该服务随用户登录启动；无人登录也要运行时，可由使用者选择配置系统的用户 linger。Docker 服务需要正常启动。不要同时运行手动 supervisor 和用户服务。

Windows 可在项目目录用 PowerShell 注册当前用户登录后的启动项：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Install-Startup.ps1 -Distro Ubuntu
```

任务名为 Dafeiyu。Docker Desktop 同样需要设置为登录后启动；此入口不能绕过微信自身的登录确认。

## 手机访问

在运行本项目的 Linux／WSL 中安装 [Tailscale](https://tailscale.com/download/linux)，完成电脑端与安卓手机端登录同一账号。然后执行：

```bash
.venv/bin/python scripts/manage.py mobile
```

按 Tailscale 官方页面完成首次 Serve 授权后，工具保存这台电脑自己的私有 HTTPS 地址及主人身份。手机连接 Tailscale 后打开该地址，可添加到主屏幕。默认不提供公网网站或免登录公共访问，也不继承维护者的 tailnet。

## 升级与备份

升级前停止桥接。备份 `data/`、自己的 `config/*.json`、`resources/` 和插件模型／音频目录；这些属于私人备份，不能上传到公开仓库。

新版本解压到单独目录，先阅读版本说明，再迁移自己的配置与数据。不要把 `.example.json` 覆盖到正在使用的配置上。普通代码升级不要求删微信数据、重新创建账号或重新下载模型。需要升级微信版本时才按新版本说明重建镜像。

卸载：停止桥接，运行 `docker compose down`，按需禁用 `dafeiyu.service` 或删除 Windows 的 Dafeiyu 启动任务；备份后自行删除项目目录。`docker compose down` 不删除绑定挂载的数据目录。不要删除其他项目的 Docker 镜像、容器或 DSH profiles。
