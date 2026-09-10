[English](README.en.md) | [简体中文](README.md) | 繁體中文 | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Italiano](README.it.md)

# 🧊 Smoothie Reader (Reader3)

> 「當技術被 AI 民主化，審美與以人為本的設計便成了最終的護城河。」

靈感源自 Andrej Karpathy 的 [極簡閱讀器原型](https://x.com/karpathy/status/1990577951671509438)，Smoothie Reader 是一個本地部署的 AI 智能電子書閱讀器，集成劃詞查詞、AI 翻譯與對話、TTS 朗讀、高亮筆記等功能，為深度閱讀而生。

📖 **內置示例書籍**：倉庫預置了馬可·奧勒留的《沉思錄》（來源於 Project Gutenberg），克隆後即可體驗。

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>個人藏書館：封面牆一覽無餘</sub>
</div>

## ✨ 核心功能

- 🔍 **直覺探索**：選中文字秒開工具欄。內置支持 **ECDICT 英文詞典** 和 **中文離線詞典**。
- 🤖 **AI 增強閱讀**：
  - **行內翻譯**：一鍵獲取高質量上下文翻譯，優雅地內嵌於原文下方。
  - **AI 伴讀**：側邊欄 AI 助手支持流式輸出和多輪記憶，隨時進行深度對話。
  - **廣泛兼容**：內置 OpenAI、Anthropic、Gemini、DeepSeek、Grok、阿里雲百煉、火山引擎、騰訊混元、MiniMax、月之暗面、矽基流動、Cerebras、SambaNova、Groq、Mistral、DeepInfra、Together AI、OpenRouter、智譜AI、ModelScope 共 20 家 AI 服務商，並支持任意 OpenAI 兼容接口自定義接入。

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>劃詞工具欄 · 行內翻譯 · AI 伴讀側欄</sub>
</div>

- 🔊 **TTS 朗讀**：基於 Edge-TTS，提供中英文多種高質量語音，解放雙眼。
- ✏️ **高亮筆記**：5 色高亮、行內筆記、書籤，所有數據存儲在瀏覽器**本地 localStorage** 中。

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>三欄閱讀：目錄導航 · 沉浸正文 · 多色高亮</sub>
</div>

- 🎨 **極簡審美**：6 種精選主題、靈活的三欄佈局（目錄/正文/AI），適配所有設備。

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>主題、排版、詞典、AI 模型 —— 一站式配置</sub>
</div>

## 🚀 快速開始

本項目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 環境和依賴。

### 1. 安裝 uv
確保系統已安裝 Python 3.10+，然後安裝 `uv`：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 導入電子書並啟動
```bash
# 導入一本 EPUB 電子書
uv run reader3.py your_book.epub

# 啟動服務
uv run server.py
```
然後打開瀏覽器訪問：👉 **http://localhost:8123**

### 3. 配置 AI
進入閱讀頁面，點擊左上角 **設置 (Settings)**，配置您的 **AI 提供商**和 API Key（例如，[免費獲取 Gemini Key](https://aistudio.google.com/apikey)）。

> [!TIP]
> **🚀 秘密通道 (秘籍)**：在頁面任何地方，依次按下 **`↑ ↑ ↓ ↓ ← → ← → B A`** (Konami Code)，即可解鎖隱藏的 **高級 AI 路由管理面板**。

## 🛡️ 隱私保護
- **本地優先**：除了您主動觸發的 AI 或 TTS 請求外，沒有任何數據會離開您的設備。
- **無需帳號**：您的數據僅保存在瀏覽器 `localStorage` 中。

## 📚 使用指南
詳細的配置說明（如離線詞典下載、多設備訪問、端口修改），請參閱 [使用指南](docs/GUIDE.md)。

## 📄 許可證
[MIT License](LICENSE)
