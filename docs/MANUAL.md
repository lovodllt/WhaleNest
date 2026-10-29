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

## 界面定位与模板

保留控件名称与无障碍接口定位。语音按钮找不到控件时，再使用随包提供的图标模板；引用与语音转文字先确认消息控件、原文或时长，再在该消息范围内匹配气泡边缘，不扫描整个聊天猜消息。低于阈值或出现多个匹配时停止操作；引用失败仍可普通回复。

模板配置位于 `data/wechat/weagent/ui_layout.json`，图片位于同级 `ui_templates/`。`region` 使用相对窗口的 `[左,上,右,下]`，取值为0到1；`scales` 控制缩放搜索。手动设置的像素 `roi` 优先于 `region`。启动时自动补齐缺少的配置字段和默认模板，保留已有配置值与同名模板文件；自定义 `template_dir` 时需自行把新增模板放入对应目录。默认模板来自 Linux 微信4.1.13.26的浅色界面，只包含通用按钮和气泡边缘，不含头像或聊天内容。当前仍保留固定窗口尺寸，不能据此宣称已适配任意版本、主题和缩放。

补充模板时，从容器微信画面保存原始PNG截图，保持实际显示比例。语音面板需包括“发语音”“发送语音”“取消”；消息菜单需包括“引用”；气泡只截不含文字的边缘。尽量避免鼠标悬停高亮，裁剪后在对应操作的搜索区域验证，未验证的模板不要直接替换发送按钮。

头像无需人工截图：辅助程序按稳定微信账号从联系人库读取小头像地址，缺少小图时用大图，在 `data/wechat/weagent/avatar_templates/` 缓存，并在头像地址变化或缓存超过6小时时重新获取。新设备登录并同步联系人后会自行建立缓存，昵称、备注变化不改变身份绑定。头像和缓存不进入源码包。

原生@先核对消息作者，再在这条消息范围内匹配对应头像，最后选择“@TA”菜单；不以昵称或头像单独认人。缩略图缺失、匹配不唯一或菜单不可用时，发送普通消息。窗口与模板适配仍有版本、主题和缩放边界，不能把头像获取成功视为所有界面动作都已验证。

普通图片由本地数据库与文件缓存读取，不需要打开或切换聊天窗口。引用的原图未进入素材缓存时，按同一聊天内的原消息编号查找，不取临近图片代替。微信本地尚无可读图片文件时仍可能读取失败。

需要界面操作的语音转写、发送及引用，会在取得界面锁后记录当前窗口，操作结束或出错后尝试激活原窗口，再释放锁。原窗口已关闭时无法恢复；该操作不恢复聊天滚动位置，也不自动关闭新开的独立聊天窗口。

## 网络问题

Docker Hub 无法访问时，可以明确选择镜像源重新构建，示例：

```bash
DAFEIYU_REGISTRY_MIRROR=mirror.gcr.io .venv/bin/python scripts/manage.py build
```

该参数只影响这次构建的基础镜像地址，不修改 Docker 全局配置或系统网络。镜像源也可能受当地网络影响。Debian 软件源可通过 Docker 构建参数 `APT_DEBIAN_MIRROR`、`APT_DEBIAN_SECURITY_MIRROR` 指定；保留版本与校验规则。

“没有收到消息”先区分：微信未登录、DSH 模型配置错误、插件缺少、暂停回复、没有匹配唤醒条件。查看控制台状态及 `data/logs/bridge.log`、`data/chat/dsh-diagnostics.log`。不要把微信未登录误判为模型断连，也不要通过重复重建容器处理模型配置问题。

微信已显示聊天列表而 `/healthz` 为 `ready:false` 时，检查 `docker compose logs --tail=30 wechat`。Webox 需要自动提取本地数据库密钥；`readable_processes` 和 `scanned_bytes` 只说明读过相关进程，不能证明持有数据库的主进程已被读全。失败日志的 `processes` 按 PID 提供读取量、映射量和明文候选数，可与微信主进程核对；不包含密钥、账号或聊天内容。

明文密钥扫描没有命中时，程序再尝试读取 WCDB 混淆的密钥缓冲区，候选必须通过对应数据库的只读打开验证才使用；`masked_candidates` 是这条路径检查的缓冲区数量，不等于验证成功的密钥数。此兼容补丁已通过临时加密数据库检查，Windows＋WSL2 的实际故障现场仍需更新后验证。补丁位于容器内，须按升级步骤重建镜像；保留 `data/wechat/`，不要为了排查删除微信数据或把其他账号的 `wechat.key` 复制过来。

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

先停止本项目，备份 `data/`、自己的 `config/*.json`、`resources/` 和插件模型／音频目录；这些属于私人备份，不能上传到公开仓库。使用自启服务时，先 `systemctl --user stop dafeiyu.service`，避免更新过程中自动重启。

通过 Git 安装的用户在原项目目录更新：

```bash
bash stop.sh
git pull --ff-only
.venv/bin/python scripts/manage.py build
bash start.sh
```

本次更新包括容器内的界面定位程序和模板，因此需要重新构建镜像；微信仍固定为4.1.13.26。以后只修改主程序或网页时可跳过构建，按更新说明操作即可。构建复用原有微信安装包；缺少安装包时先运行 `.venv/bin/python scripts/manage.py wechat-package`。Python依赖有变化时更新 `config/requirements.txt` 对应环境，DSH插件依赖有变化时运行 `.venv/bin/python scripts/manage.py plugins`；本次无需重装这些依赖。

`start.sh` 会使用更新后的镜像启动容器，保留挂载的微信数据与头像缓存；定位配置自动补齐缺少的字段，不覆盖自定义值或同名模板。聊天记录、记忆、任务、主人绑定、素材和模型沿用原目录，无需重新配置或下载。微信自身仍可能要求手机确认或重新登录。若有自启服务，更新完成后先 `bash stop.sh`，再 `systemctl --user start dafeiyu.service`，恢复单一启动入口。

如果 `git pull` 提示本地源码有修改，先保存并处理这些修改，不要强制覆盖。通过 ZIP 安装的用户将新版解压到单独目录，迁入自己的配置、`data/`、`resources/` 和模型／音频目录，再按手动安装步骤创建运行环境并构建启动；绝对路径变化时相应调整配置。不要用 `.example.json` 覆盖使用中的配置，也不必重新运行交互式配置向导。

卸载：停止桥接，运行 `docker compose down`，按需禁用 `dafeiyu.service` 或删除 Windows 的 Dafeiyu 启动任务；备份后自行删除项目目录。`docker compose down` 不删除绑定挂载的数据目录。不要删除其他项目的 Docker 镜像、容器或 DSH profiles。
