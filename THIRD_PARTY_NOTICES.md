# 第三方来源与许可说明（发布准备稿）

本文件记录实际分发前需要保留的来源说明。本包包含 Webox 及修改过的辅助程序，随附其 LICENSE、LICENSES 和 THIRD_PARTY_NOTICES；不附模型、原始角色设定图或私人数据。NPM、Python 和系统依赖由使用者安装并保留各自声明。

## 程序代码

- Webox：本机源文件标注 MIT，修改后仍保留原作者的版权与许可证。
- Webox 的 `internal/wechatdb/wechatdb.go` 有来自 wx-cli 的 Apache-2.0 部分，见上游 `THIRD_PARTY_NOTICES.md` 和 `LICENSES/Apache-2.0.txt`；不能因 Webox 主许可证为 MIT 而省略该部分声明。来源仓库目前 HTTP 451，正式发布前单独核查，不通过镜像绕过访问限制。
- DeepSeek Harness、Mnemon、modsearch 和 dsh-kaomoji：本机已安装包声明 MIT，实际分发时记录精确版本并保留声明。
- ZXing-C++ Python 绑定：二维码解码依赖 `zxing-cpp==3.1.1`，按随包 Apache-2.0 许可证及版权声明处理；通过基础依赖安装，不复制其源文件。
- psutil `7.2.2` 使用随包 BSD-3-Clause 许可；Windows 时区依赖 tzdata `2026.6` 使用随包 Apache-2.0 许可，时区数据本身保留其 IANA 来源声明。这些依赖由安装器安装，不改标为本项目原创代码。
- GPT-SoVITS 与 Amphion：程序仓库声明 MIT，模型权重另按各模型来源处理。
- Seed-VC：本机代码许可为 GPL-3.0。唱歌插件保留其来源和许可，不把第三方代码改标为本项目原创代码的许可证。
- edge-tts、FFmpeg 及其他依赖以实际分发版本的随附许可证为准，不仅依据 GitHub 自动识别结果判断。
- Kirara、export-wechat-emoji 与 wechat-emoticon 作为实现参考列明，不表示已复制这些项目的源代码；若后续引入代码，应另核对与保留对应声明。
- WCDB 密钥缓冲区的公开技术说明参考 ChisBread/wechat-ai（GPL-3.0）与 TANGandXUE/wcdb-key-tool（MIT）。本项目的 Go 扫描和验证实现独立编写，没有引入这两个项目的源文件、程序或依赖，不将其许可改标为本项目许可。

## 模型与素材

- 程序仓库许可不自动覆盖预训练模型、训练数据、参考音色或角色图片。
- ai-chan-sheets：本机原仓库 LICENSE 将补全工作标为 CC BY-NC-SA 4.0，同时明确参考原图不在该许可范围内，原始角色形象与设定归 ZipZipPipe。本项目不随包分发这些图片。
- 界面与 README 的生成插图参考 DeepSeek 娘角色设定，随包提供既有界面插画和文档配图；不附原始设定集。角色形象与参考作品的权利仍归各自权利人，生成方式与提示词记录于 `web/assets/` 和 `docs/assets/`。
- Vevo2：2026-10-26 的模型来源元数据声明 CC BY-NC-ND 4.0，不能按 Amphion 代码的 MIT 许可处理。
- 模型来源、上游声明的许可和核对时的版本号记录于来源清单；这些版本仅表示核对结果，不等于已经完成兼容性测试。
- 无明确许可的素材只记录原始出处，不声称可自由商用或再分发。用户自行导入的素材不进入项目发布包。

README 的鸣谢与本文件都不能代替实际分发代码所需的许可证全文。正式安装包、源码包与镜像应根据各自包含的文件分别保留相关声明。
