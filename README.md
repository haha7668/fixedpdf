[English](README.en.md) | 简体中文

# Smoothie Reader (Reader3) — AI 文档阅读器

> 一个面向**英文技术手册**（寄存器手册、芯片手册、IP Product Guide、学术论文）的本地部署 AI 双语阅读器。基于开源项目 [Smoothie Reader](https://github.com/Golden0Voyager/smoothie-reader) 深度定制，补齐了 PDF 阅读、双语对照翻译、多模态图片识别、本地模型接入等能力。

---

## 📌 上游来源

本仓库 fork 自以下开源项目：

| 项目 | 地址 | 许可证 | 说明 |
|------|------|--------|------|
| **Smoothie Reader (Reader3)** | [Golden0Voyager/smoothie-reader](https://github.com/Golden0Voyager/smoothie-reader) | MIT | 本项目基础，提供 EPUB 阅读器、AI 对话、TTS、高亮笔记等核心框架 |
| **Andrej Karpathy 极简阅读器** | [x.com/karpathy](https://x.com/karpathy/status/1990577951671509438) | 灵感来源 | 上游项目的设计灵感 |

## 🔗 开源依赖引用

本仓库直接使用的开源库/服务：

| 类别 | 名称 | 用途 |
|------|------|------|
| Web 框架 | [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn) | 后端服务 |
| PDF 处理 | [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF 文本/段落/坐标提取、目录解析 |
| 电子书 | 标准库 `zipfile` + `xml.etree` | EPUB 解析（自研，替代 EbookLib） |
| 语音 | [Edge-TTS](https://github.com/rany2/edge-tts) | 文本朗读 |
| HTTP | [httpx](https://github.com/encode/httpx) | AI API 调用 |
| AI SDK | [google-genai](https://github.com/googleapis/python-genai) | Gemini 接入 |
| 前端 PDF 渲染 | [pdf.js](https://github.com/mozilla/pdf.js) (Mozilla) | 浏览器端 PDF 渲染 + 文字选择层 |
| Markdown 渲染 | [marked](https://github.com/markedjs/marked) | AI 输出的 Markdown → HTML（含表格等 GFM 语法） |
| HTML 安全清洗 | [DOMPurify](https://github.com/cure53/DOMPurify) | AI 输出 HTML 防 XSS 清洗 |
| 流程图 | [mermaid](https://github.com/mermaid-js/mermaid) | AI 输出的 Mermaid 流程图渲染 |
| 离线词典 | [ECDICT](https://github.com/skywind3000/ECDICT) | 英文划词查词 |

---

## ✨ 新增功能（相对上游）

### 1. PDF 阅读与保留版式翻译（核心新增）
- **PDF 阅读器**：基于 pdf.js，支持目录导航、划词选择、全文搜索、高亮笔记、缩放。
- **中文 PDF（保留版式）**：识别真实表格单元格，带上下文翻译，后端生成 PDF；网页预览与下载复用同一份文件，不再使用 HTML 覆盖层。
- **原文保护**：保留数字、图表和线框。译文溢出、结构或字符校验失败时保留原文，并列出待检查原因。扫描件、旋转页暂不自动翻译。
- **导出**：支持下载当前页，或确认后翻译并下载整本；详见 [结构化 PDF 翻译说明](docs/pdf_translation.md)。
- **按需 + 预测翻译**：只翻译可见页，自动预翻译下方页面（`IntersectionObserver`）。
- **翻译缓存持久化**：中文 PDF、质量报告及单元格审计数据保存在书籍目录的 `.translated/` 下，按源文件内容、模型配置和引擎版本隔离；支持重试当前页。

### 2. 网页内 AI 服务商配置
- 在设置面板直接配置服务商（20+ 家 + 自定义 + Ollama + 本地 CLI），无需改代码。
- 支持「模型」「视觉模型」「Base URL」「CLI 命令模板」分别配置，含测试/保存按钮。

### 3. 多模态图片输入
- 输入框支持**粘贴图片**（Ctrl+V）和**点击上传**（可多选），随文字发送给视觉模型。
- 聊天记录中显示已发送的图片。

### 4. 智能模型路由
- 有图片 → 优先用「视觉模型」；无图片 → 优先用用户选择的模型，未配置时才用服务商默认模型。
- 翻译任务通过统一服务商路由，遵守当前配置；不会自行更换模型。

### 5. 本地模型接入
- **Ollama**：走 OpenAI 兼容接口（`http://localhost:11434/v1`），无需 API Key。
- **本地 CLI**：通过后端子进程调用 Cursor CLI、Codex 等（命令模板支持 `{prompt}` 占位符）。

### 6. 交互增强
- **「查」= AI 解释**：选中术语点「查」用 AI 解释「这是什么」；「译」= 纯翻译，职责分离。
- **多轮上下文记忆**：AI 对话携带历史，支持「用中文回答」等上下文指令。
- **悬浮卡片拖动**：翻译/查询结果卡片可拖动，位置记忆。
- **发送按钮**：输入框右下角独立发送按钮（保留 Enter 发送）。
- **荧光笔覆盖 + 白色擦除**：颜色不再叠加，白色荧光笔用于清除高亮。
- **AI 对话记录持久化**：`chat_history.json`，按书存储，跨浏览器/设备恢复。
- **Mermaid 流程图渲染**：AI 输出的 Mermaid 流程图直接渲染成图形。
- **Markdown 渲染升级**：用 marked + DOMPurify 替代手写正则，完整支持表格、代码块、引用等 GFM 语法。

---

## 🐛 修复的 Bug（相对上游）

| # | 问题 | 修复 |
|---|------|------|
| 1 | **书库被误删（严重）**：`auto_import_default_books()` 将整个 `books/` 目录传给 `process_epub()`，其内部 `shutil.rmtree()` 会删除整个书库，且「已导入」检查目录名缺 `_data` 后缀，导致每次重启都可能删书 | 改为导入到独立子目录 `{name}_data/`，不再触碰书库根目录 |
| 2 | **Windows GBK 编码崩溃**：首次启动打印 emoji 触发 `UnicodeEncodeError` 崩溃 | 启动时设置 `PYTHONUTF8=1` |
| 3 | **推理模型返回空**：`deepseek-v4-flash-vision-exp` 等推理模型把结果输出在 `reasoning_content`，`content` 为空且 `max_tokens` 被思考过程吃光 | 提高 `max_tokens`、`reasoning_content` 兜底、prompt 禁止思考 |
| 4 | **划词翻译失败**：英文划词翻译仅依赖 Google Translate（国内不可达），返回空 | 改为优先走 AI 翻译（DeepSeek），Google 作最后兜底 |
| 5 | **Markdown 标签泄漏**：手写渲染器把 `**加粗**` 转 `<strong>` 后二次转义成字面 `&lt;strong&gt;` | 改用 marked 渲染 + DOMPurify 清洗 |
| 6 | **双语译文不显示**：`.pdf-page-container` 的 `overflow: clip` 裁剪了译文块 | 改为 `overflow: visible` |
| 7 | **浮层定位错位**：`.bi-overlay` 缺少 `top: 0`，导致第一页译文偏移到第二页 | 补上 `top: 0` |
| 8 | **Mermaid 代码块被破坏**：段落处理把代码块内容塞入 `</p><p>`，导致流程图渲染失败 | 用占位符方案保护代码块 |
| 9 | **AI 对话无上下文**：每次提问独立，`用中文回答` 等指令失效 | 前端携带最近 12 条历史 + 后端拼接对话历史 |

---

## 🚀 快速开始

### 环境要求
- Python 3.10+（本仓库验证环境：Python 3.12，Windows）

### 一、Windows 双击启动（推荐）

直接双击项目根目录的 **`start.bat`**。脚本会依次检查运行环境，缺失的部分给出下载或自动安装选项：

| 检查项 | 缺失时的处理 |
|--------|--------------|
| Python 3.10+ | 可打开官方下载页，或用 winget 自动安装 |
| 虚拟环境 `.venv` | 提供一键创建并安装依赖 |
| 依赖组件 | 列出缺失的包，提供 `pip install -r requirements.txt` |
| 服务端口 | 已在运行时直接打开浏览器，避免重复启动 |

启动成功后会自动打开浏览器。**关闭该窗口即停止服务**（或按 Ctrl+C）。

只想检查环境、不启动服务：

```powershell
start.bat --check
```

### 二、手动启动（跨平台）

#### 1. 安装依赖（venv + pip）

```powershell
cd smoothie-reader
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pymupdf
```

> 说明：上游使用 `uv`，但本仓库在 Windows 环境已用 `venv + pip` 验证可用。`requirements.txt` 未包含 PyMuPDF，需额外安装。

#### 2. 启动服务（Windows 需 UTF-8 模式）

```powershell
$env:PYTHONUTF8=1; $env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe server.py
```

打开浏览器访问：**http://localhost:8123**

### 3. 配置 AI
1. 上传 PDF/EPUB → 打开书
2. 右上角**齿轮 → AI 翻译服务** → 选择服务商 → 填 API Key → 保存
3. 建议：`模型` 填 `deepseek-chat`（文本/翻译），`视觉模型` 填 vision 模型（看图）

### 4. 双语对照
设置面板打开「**双语对照翻译**」开关，选择「对照模式」（浮层 / 逐段对照 / 流式重排）。

---

## 📄 许可证

本项目采用 [GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0，Copyright (c) 2026 Haining Yu）。

> 由于本项目集成了 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)（AGPL-3.0），其 copyleft 条款要求本仓库同样以 AGPL-3.0 分发。集成各第三方开源库的许可与版权声明，请参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## 🙏 致谢

- [Golden0Voyager/smoothie-reader](https://github.com/Golden0Voyager/smoothie-reader) — 上游项目
- Andrej Karpathy — 阅读器原型灵感
- 以及上表所列全部开源项目的作者与维护者
