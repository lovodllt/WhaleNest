# 功能配置

基础聊天和定时任务不需要本地 GPU。仅启用所需功能；资源下载与模型启用分开。控制台“聊天与能力”显示当前能力和依赖，“角色与素材”提供下载、来源、大小、版本、校验和导入入口。

## 人设和角色图片

人设没有内置默认正文。可在资源中心下载上游大肥鱼人设，再选择“设为当前人设”；也可直接编辑、粘贴或导入自己的 Markdown／文本文件。保存后供后续聊天读取，不赋予额外工具权限。已有文件不会被下载操作覆盖，手动编辑会在本机保存上一版。

人物目录位于 `resources/characters/人物名/`。每个人物有 `设定.json`、可选文字说明和 `images/`；前端导入图片时自动生成基础资料文件。文件名含“设定集”的图片优先，其他图片作为辅助参考。可继续在该文件夹补充图片与文字。原始图、人设、第三方模型都不进入基础发布包。

## 记忆

在控制台开启“私聊长期记忆”。个人事实按稳定微信账号和私聊分开；只有主人私聊能影响全局性格偏好，群聊只使用近期共同讨论。

“记忆手账”支持查看、纠正、置顶、忘记、清空和重试失败提炼。普通印象默认90天，稳定事实与置顶印象不按年龄删除；容量不足时保留原文归档。模型记录和整理队列默认7天，正常提炼后清空队列原文。忘记不会删除微信客户端历史和外部模型服务日志。

需要 `dsh-mnemon` 和 `dsh-mnemon-source-runtime`；由 `manage.py plugins` 检查安装。提炼使用 DSH 配置的模型，是记忆整理，不是训练模型权重。

## 联网和识图

联网在“联网与生图”设置中开启，使用 DSH 配套 ModSearch，允许根据当前聊天需要查询公开资料。不开启时不会调用检索程序。

识图复用配置的 DSH 多模态模型；纯文字模型无法凭该开关看图。微信图片与表情媒体由 Webox 和 native-media 辅助程序接收，不通过遍历其他聊天图片猜测当前图片。

## 生图

首版保留现有的本机 Codex 生图链路。需自行安装、登录具备生图能力的 Codex，保证 `codex` 可从桥接进程的 PATH 找到，然后开启“启用 Codex 生图”。程序不随包提供 Codex 登录资料，也未提供通用生图 API 适配器。

群聊用唤醒词搭配 `/imageGen 需求`；主人私聊可按意思发起。默认不自发画图；额度和豁免通过 `config/chat.json` 的 `image.daily_limit`、`image.owner_exempt` 配置。角色图片只在已导入的情况下引用，没有设定集时不会伪称已经参考。

## 微软在线语音

安装轻量依赖：

```bash
.venv/bin/python -m pip install -r plugins/voice/requirements.txt
```

在控制台开启语音回复。默认晓伊、音高 +5Hz，参数可以在控制台或 [调音页](http://127.0.0.1:9981/) 设置。需要更多中文音色时执行：

```bash
.venv/bin/python scripts/voices.py
```

TTS 合成后通过容器内虚拟音频通道发送微信原生语音，不调用电脑扬声器。在线路线无本地模型权重，使用时需要联网。首次启用后如状态尚未更新，可停止并重新启动桥接服务；不会因此重建微信容器。

## GPT-SoVITS 本地路线

资源中心可下载 V2ProPlus 所需的基础模型文件，位置为 `resources/models/gpt-sovits/`。程序来源为 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，按上游教程在独立环境部署；将下载目录中的对应文件按上游配置映射到模型路径，并提供自己可使用的参考声音和参考文本。

本包提供 `plugins/voice/local_gpt_sovits.py` 启动桥接：在 GPT-SoVITS 的独立 Python 环境中执行，路径需要换为自己的实际位置：

```bash
python /项目路径/plugins/voice/local_gpt_sovits.py --source /上游源码路径 --reference /自己的参考音频.wav --reference-text '参考音频对应的文字'
```

默认监听本机9980，CUDA 分配器上限为整卡40%；可用 `--device cpu` 改为 CPU。随后在控制台将“语音引擎”切换为“本地 GPT-SoVITS”，并开启语音回复。默认引擎仍为微软在线语音。首次部署仍需按上游安装 GPU 依赖和准备自己的参考音频；本次打包没有重新运行重型模型做音质验收。下载成功不表示已经完成音色学习。

## 唱歌：Seed-VC

聊天端点唱发送已经准备好的清唱片段，不会把歌词当作普通 TTS 念出来。先从资源中心下载 Seed-VC 程序和下列五组模型资源：Seed-VC、VoiceConversionWebUI（RMVPE）、CAMPPlus、BigVGAN、Whisper small。文件下载到 `plugins/singing/models/`。

为唱歌创建独立 Python 环境，建议 Python 3.10；根据 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/) 安装匹配显卡驱动的 Torch，再按 [Seed-VC](https://github.com/Plachtaa/seed-vc) 的 requirements 安装其依赖。不要把大型 GPU 依赖装进基础聊天虚拟环境。

需要自己准备歌曲和参考音色：

- 将有权使用的参考声音保存为 `plugins/singing/reference.wav`。
- 使用 `plugins/singing/separate.py` 分离自己提供歌曲的人声和伴奏，需要 Demucs、Torch、NumPy、SoundFile。
- 下载固定版本的 Seed-VC 程序后，先执行 `python plugins/singing/whole_phrase.py`，应用保留的40秒上下文与4096缓存设置。
- 使用 `plugins/singing/convert.py 输入人声.wav 输出目录` 换声，需额外安装 psutil、nvidia-ml-py、PyYAML。脚本保留30步、CFG 0.7、原调原速，以及6GiB整卡使用上限；不同显卡和音频长度的占用需要自己观察。
- `convert.py` 下载前不执行推理，不自动播放，也不自动发微信。

在 `config/chat.json` 中启用已收录歌曲，并指向实际准备的 PCM16 WAV 片段，例如：

```json
"singing": {
  "enabled": true,
  "default_song": "自己的歌曲",
  "songs": {
    "自己的歌曲": {
      "path": "resources/songs/自己的歌曲-30秒.wav",
      "aliases": ["自定义简称"]
    }
  }
}
```

微信原生语音发送范围为1至55秒。来源较长的歌曲请先裁剪；缺少音源的点唱会说明未准备，不用 TTS 代唱。歌曲、参考音色和历史试听不随包提供。

Vevo2 保留为实验对比，其模型和 Whisper medium 也可选下载。相关脚本位于 `plugins/singing/vevo2/`，需要按 [Amphion／Vevo2](https://github.com/open-mmlab/Amphion) 的上游说明另配环境。首版不默认安装或加载；其模型许可与 Seed-VC 不同。

## 日常行动和主动参与

主人生活工具默认关闭。开启后只有本机真实绑定主人的私聊获得已实现的素材整理、提醒与日常设置工具；不开放任意终端、文件操作或工作代办。

自然参与与主动消息分别配置；未配置白名单时不主动发送消息。群聊自然参与仍要求最近10分钟出现唤醒词，并由模型判断是否值得回应，不是逐句回答。
