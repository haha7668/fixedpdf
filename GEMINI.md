# Project Intelligence: Reader3

一个现代化的、支持 AI 交互的 EPUB 阅读器。

## 🧠 项目特有逻辑
- **核心功能**: 负责 EPUB 全文翻译、内容摘要及 TTS 文本预处理。
- **音频引擎**: 强制使用 Edge-TTS，见 `tools/` 封装。

## 📁 隔离规范 (Isolation)
- **数据缓存**: `books/` 目录下的解析结果和 `cache/` 音频严禁提交。
- **字典**: `dict/` 下的本地词库不被跟踪。