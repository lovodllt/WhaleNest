# 微信实时语音通话

从「编写自主虚拟人物系统 v0.3 规范」任务的 Dworld 实现迁入，适配 WhaleNest 的本机 DSH、人设、主人绑定、记忆和发送队列。代码可独立分发，不导入 Dworld 程序、联系人、数据库或私有配置。

## 范围

支持绑定主人的微信一对一语音通话：限时等待一次来电，或由操作员明确发起一次呼出。默认关闭，没有永久自动接听、人物自行拨号或自动重拨。仅支持 Linux / WSL2 的 Docker 微信，Windows 原生主控暂不支持实时通话。

这与原来的微信语音消息、唱歌功能分开，现有线路保留。通话使用 CPU SenseVoice INT8 识别与 Silero VAD，人物回复通过同一配置的本机 DSH 模型；流式 Edge TTS 沿用 `config/voice.json` 的音色、音高、语速。没有新增直接调用模型 API 的通路。

## 安装

在已经完成 WhaleNest 初始化、登录微信并绑定主人私聊的实例中操作：

```bash
.venv/bin/python -m pip install -r plugins/voice/call/requirements.txt
cp config/voice-call.example.json config/voice-call.json
```

宿主还需要 FFmpeg（Ubuntu 可用 `sudo apt install ffmpeg`）。在控制台资源中心分别下载「通话识别 · SenseVoice INT8」和「通话检测 · Silero VAD」。合计约241MB，放到 `resources/models/voice-call/`，不占显存，不因下载而启用通话。

也可以按 `config/resources.json` 内固定版本的原始链接手动下载，保留文件名和许可文件，并按清单校验大小、SHA256或Git blob SHA1。来源为 [SenseVoice ONNX 模型](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17) 与 [Silero VAD 转换模型](https://huggingface.co/csukuangfj/vad)；API用法参照 [sherpa-onnx 官方文档](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)。模型许可与 sherpa-onnx 程序许可分开处理。

编辑仅保存在本机的 `config/voice-call.json`：

| 字段 | 内容 |
| --- | --- |
| `enabled` | 改为 `true` 才允许通话 |
| `caller_names` | 本人实际来电显示名称数组，填本实例的微信备注或显示名；不要填群名 |
| `container` | 默认 `dafeiyu-wechat` |
| `python` | 留空使用当前 Python；也可填写装好通话依赖的专用解释器路径 |
| `models` | 默认 `resources/models/voice-call`，支持项目相对路径 |
| `ffmpeg` | 默认使用 PATH 中的 `ffmpeg`，可指定路径 |
| `fast_mode` | 仅通话 profile 使用同一 DeepSeek 模型的非思考模式；其他提供方改为 `false` |

姓名匹配是界面层约束，不能防止其他人使用相同显示名，首次绑定时请核对真实联系人窗口。程序要求本实例已绑定主人，且只接受唯一匹配窗口，不能用昵称授予他人权限。

生成新增的通话专用 DSH profile，再检查依赖：

```bash
.venv/bin/python scripts/manage.py profiles
.venv/bin/python scripts/voice_call.py --check
```

修改 `fast_mode` 后须重新生成 profiles。该操作只更新本项目管理的 profiles，不修改其他 DSH 配置。普通聊天模型不切换模式。控制台的暂停回复开关仍有效，暂停时不能接通或继续通话。

## 使用

只读查看可访问性控件，不接听、不拨号：

```bash
.venv/bin/python scripts/voice_call.py --probe
```

限时等待本人来电，接一次后退出：

```bash
.venv/bin/python scripts/voice_call.py --wait --wait-seconds 180 --max-call-seconds 600
```

明确要拨给主人时，先在微信中打开绑定本人的**独立私聊窗口**，再运行：

```bash
.venv/bin/python scripts/voice_call.py --dial-owner --max-call-seconds 600
```

使用可访问性标签和实时控件矩形定位接听、挂断、语音通话菜单，不依赖固定屏幕坐标。无法唯一确定时退出，不猜点。Ctrl+C、SIGTERM、通话时限、对端挂断、关闭通话或暂停回复都会触发清理；出错不自动重拨。

## 对话、打断与记忆

- 每轮使用独立的 DSH 会话和精简提示，携带最近24条通话条目、最近12条普通文字/已转写语音背景、当前人设与性格偏好。启用记忆时检索同一主人私聊的长期记忆。没有复用普通聊天的长窗口，也不需要等待长窗口达到换窗阈值。
- 通话只开放说话和挂断，不加载主人行动、B站或联网工具。回复以短口语为主，可保持倾听；模型返回损坏JSON会被拒绝，短纯文本可作为一句口语处理。
- VAD以450毫秒静音分句。用户开始说话立即停止旧播放、更新回复代次；旧模型或旧合成结果不再播放。连续发言等识别队列清空后合并理解。
- 原始通话音频不落盘。转写进入原有私聊上下文；启用记忆后沿用原记忆提炼队列。只有完整播完的回复才写成已说内容，打断或无法确认的音频不重播。清除该会话记忆会使在途通话失效。DSH本身会按配置保存会话与诊断文件，通话目录为 `data/chat/call-sessions/`。

## 队列与音轨

通话持有本机 `data/chat/conversation.lock`，普通微信回复保持排队，接收线程继续收消息。容器侧使用与原生发送/语音转文字相同的 `/webox/state/weagent/ui-send.lock`。已在生成或发送的普通回复结束前，不抢占其界面。

从旧版升级时，先重新启动 WhaleNest 桥接以加载新增的发送互斥，再启用通话；旧进程不会自动加载新代码。本次迁移不替使用者重启或启用服务。

微信下行只进入 `whalenest_call_rx.monitor`，上行只写已有 `voice_bus → dafeiyu_mic`。不调用主机物理麦克风或扬声器。结束时停止本项目的录放音进程、恢复容器原默认音轨并卸载接收轨。不要同时运行其他项目控制同一微信，也不要在通话中手工操作发送界面。

## 验证边界

源任务曾完成真实呼出和双向语音；其少量样本的转写就绪到首次送音频约4–6秒，不能当作迁移后或实际听见的延迟保证。识别分句、网络模型与在线TTS均会增加等待，当前不是模型token级流式出声。

本次在 WhaleNest 中仅做隔离的逻辑、队列、音轨命令与异常清理检查，没有拨号、接听或播放电脑音频。迁移后的真实来电、呼出与长期稳定性仍须在使用者自己的微信环境验收。
