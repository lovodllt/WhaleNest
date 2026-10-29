# 鸣谢与来源

感谢以下开源项目及其贡献者。以下区分实际依赖、可选资源和实现参考，不将仅参考过的项目描述为运行依赖。

### 核心接入与运行依赖

| 项目 | 本项目中的用途 |
| --- | --- |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | 本机模型会话、工具调用与插件宿主 |
| [Webox](https://github.com/netcat-ai/webox) | Docker 内 Linux 微信及消息接口；本项目维护额外适配与辅助程序 |
| [dsh-mnemon](https://github.com/omdsh-dev/dsh-mnemon) | Mnemon 记忆存储和 Runtime Source；本项目另做作用域、提炼与管理界面 |
| [modsearch](https://github.com/liustack/modsearch) | 简单公开联网查询 |
| [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp) | 本机二维码解码，使用 Python 绑定 |
| [dsh-kaomoji](https://github.com/TianJie52009/dsh-kaomoji) | 颜文字插件 |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) | 微信界面文字和目标定位辅助 |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | 媒体处理；具体构建所包含的组件另行列明 |
| [Tailscale](https://github.com/tailscale/tailscale) | 可选的手机私有远程连接 |

### 可选语音、唱歌与角色资源

| 项目 | 本项目中的用途 |
| --- | --- |
| [edge-tts](https://github.com/rany2/edge-tts) | 微软在线语音接入与音色参数调整 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 保留的本地语音与音色模仿方案 |
| [Seed-VC](https://github.com/Plachtaa/seed-vc) | 当前首选唱歌换声方案 |
| [Amphion](https://github.com/open-mmlab/Amphion) | Vevo2 实验换声方案 |
| [Demucs](https://github.com/facebookresearch/demucs) | 人声与伴奏分离 |
| [BigVGAN](https://github.com/NVIDIA/BigVGAN) | 声码器 |
| [Whisper](https://github.com/openai/whisper) | 换声编码器相关组件 |
| [dafeiyu-persona](https://github.com/ERUIHNIYHBKBNF/dafeiyu-persona) | 可选人设来源，仅提供下载入口 |
| [ai-chan-sheets](https://github.com/lmy414/ai-chan-sheets) | 可选角色补全设定来源；原始角色形象归 ZipZipPipe，见原仓库授权说明 |
| [deepseek-chan-meme-pack](https://github.com/the-beating-light-of-the-nail/deepseek-chan-meme-pack) | 可选表情包来源，仅提供来源与导入入口 |

### 实现参考与上游来源

- [Kirara AI](https://github.com/lss233/kirara-ai)：参考消息触发、会话作用域和多模态工作流设计；本项目不以 Kirara 作为运行框架。
- [export-wechat-emoji](https://github.com/liusheng22/export-wechat-emoji)：参考表情图片缓存和复用方式。
- [wechat-emoticon](https://github.com/spacelan/wechat-emoticon)：参考表情消息中的 MD5、CDN 元数据提取思路。
- [wx-cli](https://github.com/jackwener/wx-cli)：Webox 的部分微信数据库解析代码注明来自该项目，保留上游 Apache-2.0 来源说明。2026-10-26 核对时该仓库返回 HTTP 451；不提供替代下载地址，该项列入正式发布前核查。
- [wechat-ai](https://github.com/ChisBread/wechat-ai)、[wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)：参考 WCDB 混淆密钥的公开技术说明，Go 兼容实现独立编写，候选使用现有 SQLCipher 驱动验证；两者不是运行依赖。

主要上游来源的核对记录见 [来源核对记录](upstream-sources.json)，第三方许可处理见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。正式发布时随实际分发内容补齐对应许可证全文、版权声明、修改说明和依赖版本。
