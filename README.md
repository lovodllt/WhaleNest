# 鲸栖 WhaleNest

鲸栖是一个跑在本机 DSH 上的微信陪伴工作台。它把微信接入、角色工作台、记忆和定时任务收进同一个入口，默认角色是大肥鱼。想添置声音或素材时，再按需打开对应能力。当前为 0.1.0 预发布版本。

![鲸栖：给本机 AI 留一个小窝](docs/assets/whalenest-hero.png)

## 功能一览

微信接入、消息排队、网页控制台和定时任务统一内置；其他能力在同一个工作台配置，所需插件与模型按需安装。

| 类别 | 基础内置 | 可选 / 按需 |
| --- | --- | --- |
| 聊天与记忆 | 微信消息接入、接收排队、回复发送、唤醒与自然参与、网页控制台 | 记忆存储与作用域管理（dsh-mnemon）、联网查询（ModSearch） |
| 图片与素材 | 资源管理与手动导入 | 多模态识图、本机 Codex 生图、角色图与表情包 |
| 声音 | 微信语音接收与发送通道 | Edge 在线 TTS（默认引擎）、GPT-SoVITS 本地音色、Seed-VC 换声及已准备片段点唱 |
| 任务与管理 | 定时任务、资源中心、启动停止与诊断 | 手机浏览器访问；Tailscale 私有远程连接 |

## 安装与启动

### 平台与依赖

| 平台 | 首版运行方式 |
| --- | --- |
| Linux x86_64 | 直接安装 |
| Windows | Docker Desktop + WSL2 Ubuntu，在 WSL 内安装与启动 |

Windows 首版在 WSL Ubuntu 中执行同一组 bash 命令，不承诺原生 Windows 运行。

需要预先准备：

- Python 3.12
- Node.js 24
- 本机 DSH 0.2.1-rc.2
- Docker Compose

鲸栖必须使用本机 DSH，不提供绕过 DSH 的主模型直连 API。请在宿主机或 WSL 内运行 DSH 和主程序；Docker 内只运行固定版本微信 4.1.13.26 与 Webox。

### 一键安装与启停

在项目根目录执行：

```bash
bash install.sh
```

安装脚本会检查依赖与 DSH，并引导完成配置。它不会自动安装 Docker、WSL 或 DSH；缺少的部分请先按文档补齐。

启动与停止：

```bash
bash start.sh
bash stop.sh
```

打开 [鲸栖工作台](http://127.0.0.1:8877/) 和 [微信登录画面](http://127.0.0.1:6860/vnc.html)。按向导配置自己的模型服务，登录微信并绑定主人后开始聊天。详细步骤见 [快速开始](docs/QUICKSTART.md)。

## 版本状态

0.1.0 的验证范围如下：Linux 已完成独立安装与构建检查；Windows 尚未进行实体设备端到端验证，具体见 [验证记录](docs/VERIFICATION.md)。当前仍有未覆盖的验证项目，请以记录为准。

## 角色、素材与下载

人设、角色图、表情包、语音和唱歌权重、音源均不随项目打包。前端默认提供管理、手动导入和可选下载；原始链接完整保留在 [资源与下载](docs/RESOURCES.md)。

资源目录与程序目录分离，升级时不会覆盖你补充的设定和素材。下载完成后会校验文件，但不会自动加载模型；是否启用由你决定。

README 中的插图是文档配图，与第三方角色设定无关。角色素材的使用请遵循各自来源的许可。

## 能力边界

生图使用现有本机 Codex 链路，并非已经支持通用生图 API；识图依赖你配置的多模态模型。默认语音是 Edge 在线 TTS，无需本地语音模型，但使用时要联网；GPT-SoVITS 和 Seed-VC 是可选方案。唱歌会发送你自己准备的片段，不承诺凭任意歌名实时生成。

## 给 Agent 的指引

接手项目时，请先读 [AGENTS.md](AGENTS.md)。

项目尚未配置时，先运行环境检查 `python3 scripts/manage.py check`，再按文档安装；不要跳过检查直接改运行环境。

不要读取密钥，不要复用维护者的私有数据，不要自动发送测试消息。需要测试时使用独立数据目录，避免接触真实的聊天、记忆和登录态。

## 文档入口

- [快速开始](docs/QUICKSTART.md)：环境准备、安装与首次配置。
- [手动安装](docs/MANUAL.md)：Linux 与 Windows/WSL2 的详细步骤。
- [功能说明](docs/FEATURES.md)：能力范围、可选组件与使用方式。
- [资源与下载](docs/RESOURCES.md)：人设、素材、模型和原始来源。
- [验证记录](docs/VERIFICATION.md)：已检查项目与尚未覆盖的范围。
- [AGENTS.md](AGENTS.md)：Agent 协作、环境检查和测试约定。

## 数据与配置

主人绑定、聊天数据库、长期记忆、声音样本、登录态和密钥保存在自己的运行目录，不进入发布包。使用在线模型、检索或在线语音时，相关输入会交给你所配置的服务处理。每位使用者自行绑定设备、主人身份和微信账号；导出的备份属于私人数据，请与公开分发内容分开保管。

## 鸣谢

感谢以下项目与贡献者。它们在本项目中分别承担运行依赖、可选资源或实现参考，不能一概视为必需依赖。

感谢 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 提供本机会话、工具调用与插件宿主；[Webox](https://github.com/netcat-ai/webox) 提供 Docker 内微信与消息接口；[dsh-mnemon](https://github.com/omdsh-dev/dsh-mnemon) 提供记忆存储与 Runtime Source；[ModSearch](https://github.com/liustack/modsearch) 提供简单公开联网查询；[edge-tts](https://github.com/rany2/edge-tts) 提供微软 Edge 在线语音的接入。声音方案中的 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 与 [Seed-VC](https://github.com/Plachtaa/seed-vc) 为可选依赖；人设来源 [dafeiyu-persona](https://github.com/ERUIHNIYHBKBNF/dafeiyu-persona) 和角色设定来源 [ai-chan-sheets](https://github.com/lmy414/ai-chan-sheets) 也一并致谢。

其他依赖、可选资源与实现参考见 [docs/ACKNOWLEDGEMENTS.md](docs/ACKNOWLEDGEMENTS.md)；第三方许可、版权与修改说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目原创代码许可证待定，本文不赋予新的再分发许可；第三方代码、角色素材与模型权重分别遵守各自来源的许可。
