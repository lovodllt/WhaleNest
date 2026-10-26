# 一键配置教程

## 先准备什么

- x86_64 的 Linux，推荐 Ubuntu 24.04；Windows 使用 Docker Desktop＋WSL2＋Ubuntu。
- Python 3.11 或更新版本及 venv、Node.js 24、npm、Docker Engine／Docker Desktop 和 Docker Compose v2。
- 本机 DSH。此包针对 DSH `0.2.1-rc.2` 的 SDK 与插件配置制作；已有其他版本建议先查看 `check` 输出。
- 自己的模型服务地址、模型名称和 API Key，以及自己用于登录的微信账号。

安装 DSH：

```bash
npm install -g @deepseek-ai/dsh@0.2.1-rc.2
dsh --version
```

DSH 必须安装在实际运行桥接程序的环境：Windows 用户在 WSL 的 Ubuntu 内安装，不使用 Windows 端的 DSH 路径。

## Linux

解压安装包，在它的根目录打开终端：

```bash
bash install.sh
```

向导依次询问本机 DSH 位置、DSH 配置目录、模型 ID、模型服务地址、Docker 镜像源及密钥。密钥输入不回显，只保存到自己的 `config/secrets.json`，不要分享该文件。

随后安装专用 DSH 插件、从微信官方地址下载并校验固定版本的微信安装包、构建 Docker 镜像并启动控制台。第一次构建需要联网，耗时取决于网络。

## Windows

先安装并启动 Docker Desktop，在设置中打开 WSL2 引擎，并启用目标 Ubuntu 发行版的 WSL 集成。打开 Ubuntu，确认下列命令均可用：

```bash
python3 --version
node --version
npm --version
dsh --version
docker compose version
docker info
```

建议将项目放在 WSL 的 Linux 文件系统，例如 `~/whalenest`，然后在 Ubuntu 内运行 `bash install.sh`。如果解压在 Windows 文件系统，也可从项目目录用 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

该脚本只为本次启动使用执行参数，不修改系统执行策略；仍要求 Ubuntu 内的前置依赖已经安装。

## 微信登录和主人绑定

1. 打开 [微信登录画面](http://127.0.0.1:6860/vnc.html?autoconnect=1&resize=scale)，用自己的账号完成登录。
2. 查看可绑定的联系人：

```bash
.venv/bin/python scripts/manage.py contacts
```

3. 用唯一备注、昵称或准确的微信账号 ID 绑定主人。下面的名称需要替换为自己的联系人：

```bash
.venv/bin/python scripts/manage.py bind --owner '自己的联系人备注'
```

绑定完成后才启用聊天回复。默认私聊回复和群聊点名回复开启，自然参与、主动消息与可选功能关闭。群里的唤醒称呼为当前微信昵称或“D老师”；不要把这次安装的主人绑定误认为维护者账号。

打开 [角色工作台](http://127.0.0.1:8877/)，在“资源与人设”导入人设和角色图片，在“插件中心”“聊天与偏好”设置功能。没有下载人设也可启动基础程序，不会自动采用维护者的人设、私有教导或聊天记忆。

## 以后启动与停止

```bash
bash start.sh
bash stop.sh
```

`stop.sh` 停止本项目的 Python 服务，保留微信容器和数据；需要停止微信容器时运行 `docker compose stop`。后续再 `start.sh` 会复用原有数据目录，不需要重新构建镜像。

出错或需要自启，查看 [手动安装与故障处理](MANUAL.md)；语音、唱歌、生图等配置见 [功能配置](FEATURES.md)。
