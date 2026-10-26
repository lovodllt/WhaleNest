# 可选资源与下载

**人设、图片设定集、表情包、语音和唱歌模型权重均不内置于源码压缩包或基础镜像。** 下表提供原始来源，使用者可以自行下载；软件“角色与素材”页面提供可选的一键下载或导入入口。自带的声音样本、歌曲和私人素材不公开。

| 资源 | 原始来源／手动下载入口 | 用途 |
| --- | --- | --- |
| 大肥鱼人设 | [dafeiyu-persona](https://github.com/ERUIHNIYHBKBNF/dafeiyu-persona) | 可选的初始人设；不包含维护者的私有教导与权限规则 |
| AI娘图片与文字设定 | [ai-chan-sheets](https://github.com/lmy414/ai-chan-sheets) | 角色形象与生图参考，按人物导入 |
| 表情包参考资源 | [deepseek-chan-meme-pack](https://github.com/the-beating-light-of-the-nail/deepseek-chan-meme-pack) | 可选表情包来源，也支持用户自行导入 |
| GPT-SoVITS | [程序仓库](https://github.com/RVC-Boss/GPT-SoVITS)、[模型权重](https://huggingface.co/lj1995/GPT-SoVITS) | 可选本地语音与音色模仿 |
| Seed-VC | [程序仓库](https://github.com/Plachtaa/seed-vc)、[模型权重](https://huggingface.co/Plachta/Seed-VC) | 唱歌换声首选方案，按需安装 |
| Vevo2／Amphion | [程序仓库](https://github.com/open-mmlab/Amphion)、[模型权重](https://huggingface.co/RMSnow/Vevo2) | 保留的实验对比方案，默认不启用 |
| BigVGAN | [程序仓库](https://github.com/NVIDIA/BigVGAN)、[44kHz 模型](https://huggingface.co/nvidia/bigvgan_v2_44khz_128band_512x) | 唱歌方案的声码器依赖 |
| Whisper | [程序仓库](https://github.com/openai/whisper)、[small 模型](https://huggingface.co/openai/whisper-small)、[medium 模型](https://huggingface.co/openai/whisper-medium) | 换声方案使用的编码器；按所选方案下载 |
| CAMPPlus | [模型来源](https://huggingface.co/funasr/campplus) | Seed-VC 的说话人特征依赖 |
| RMVPE | [当前模型来源](https://huggingface.co/lj1995/VoiceConversionWebUI) | 唱歌音高提取依赖 |
| Demucs | [程序与模型说明](https://github.com/facebookresearch/demucs) | 可选的人声、伴奏分离 |

微软在线语音通过 [edge-tts](https://github.com/rany2/edge-tts) 接入，不需要下载本地语音模型，但使用时需要联网；不将其描述为离线模型或微软官方 SDK。

资源中心默认提供人设、角色与模型管理界面，不要求先下载资源才显示入口。下载前显示来源、版本、大小、用途及许可；下载完成后校验文件并放入对应目录，下载失败可重试，也支持已下载文件的手动导入。模型下载与启用分开，不因下载而自动加载模型占用显存。未配置角色素材时使用通用占位界面。

角色设定集按人物分目录，人物名作为目录名。文件名含“设定集”的图片优先作为形象依据，其他图片用于固定形象和扩展风格。模型只下载所选方案需要的文件，不将整个模型仓库全部拉取。资源目录与程序目录分离，升级不覆盖用户补充的设定和素材。

下载来源不等于任意再分发或商用授权。角色图片、程序代码和模型权重分别遵守各自来源的许可；例如 ai-chan-sheets 的补全内容与参考原图授权范围不同，Vevo2 权重也与 Amphion 程序代码的许可不同。资源管理保留这些区别；上游要求登录或授权的下载转至其官方流程，不代填账户信息。
