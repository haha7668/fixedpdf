# Third-Party Notices

本项目（FixedPDF）集成并分发以下第三方组件。根据各组件的许可证要求（AGPL-3.0、LGPL-3.0 及各类宽松许可证均要求在分发时附上版权与许可声明），在此逐项列出其版权归属与许可证。

## 上游项目

本项目 fork 自 **Smoothie Reader (Reader3)**，其 MIT 许可证原文随仓库保留，见 [`LICENSES/upstream-smoothie-reader-MIT.txt`](LICENSES/upstream-smoothie-reader-MIT.txt)。

| 项目 | 地址 | 许可证 | 版权 |
|------|------|--------|------|
| Smoothie Reader (Reader3) | <https://github.com/Golden0Voyager/smoothie-reader> | MIT | (c) 2026 Haining Yu |
| Andrej Karpathy 极简阅读器 | <https://x.com/karpathy/status/1990577951671509438> | 灵感来源 | — |

## Copyleft 依赖（对本仓库许可证有约束）

| 组件 | 许可证 | 版权方 | 说明 |
|------|--------|--------|------|
| PyMuPDF / MuPDF | GNU AGPL-3.0 或 Artifex 商业许可 | Artifex Software, Inc. | PDF 解析、文本/段落/坐标提取、排字 |
| edge-tts | LGPL-3.0（`src/edge_tts/srt_composer.py` 为 MIT） | rany2 及贡献者 | 文本朗读（TTS） |

## 宽松许可证依赖

| 组件 | 许可证 | 版权方 |
|------|--------|--------|
| FastAPI | MIT | Sebastián Ramírez |
| Starlette | BSD-3-Clause | Encode OSS Ltd. |
| Uvicorn | BSD-3-Clause | Encode OSS Ltd. |
| Pydantic | MIT | Samuel Colvin |
| httpx | BSD-3-Clause | Encode OSS Ltd. |
| Jinja2 | BSD-3-Clause | Pallets |
| beautifulsoup4 | MIT | Leonard Richardson |
| Pillow | MIT-CMU | Secret Labs AB / Fredrik Lundh / Alex Clark |
| python-dotenv | BSD-3-Clause | Saurabh Kumar |
| python-multipart | Apache-2.0 | Andrew Dunham |
| google-genai | Apache-2.0 | Google LLC |
| dashscope | Apache-2.0 | Alibaba Cloud |
| requests | Apache-2.0 | Kenneth Reitz |
| aiohttp | Apache-2.0 | aio-libs |
| tenacity | Apache-2.0 | Julien Danjou |
| cryptography | Apache-2.0 / BSD-3-Clause | Python Cryptographic Authority |
| socksio | Apache-2.0 | Seth Michael Larson |

## 开发工具依赖

| 组件 | 许可证 | 版权方 | 说明 |
|------|--------|--------|------|
| markdown | BSD-3-Clause | Waylan Limberg 及贡献者 | `tools/_md2pdf.py` 文档转 HTML |
| playwright | Apache-2.0 | Microsoft Corporation | `tools/_md2pdf.py` 浏览器渲染 |

## 前端运行时资源（浏览器加载，经 CDN）

| 组件 | 许可证 | 版权方 |
|------|--------|--------|
| pdf.js | Apache-2.0 | Mozilla Foundation 及贡献者 |
| marked | MIT | Christopher Jeffrey |
| DOMPurify | MIT / Apache-2.0 双许可 | Cure53 |
| mermaid | MIT | mermaid contributors |

## 数据 / 内容

| 组件 | 许可证 | 版权方 |
|------|--------|--------|
| ECDICT 词典数据 | MIT | skywind3000（<https://github.com/skywind3000/ECDICT>） |
| Meditations（预置电子书） | 公有领域原作；EPUB 排版来自 Project Gutenberg | Project Gutenberg |

## 第三方服务（运行时可选调用）

以下外部服务为**运行时可选调用**，均非本项目分发的内容，相关条款以其官方文档为准：

| 服务 | 用途 | 说明 |
|------|------|------|
| Google Translate | 划词翻译兜底 | 使用公开的 `translate.googleapis.com` 端点，**非官方 API**，仅供本地个人使用 |
| 豆瓣读书 | 封面搜索 | 抓取公开搜索接口，仅供个人学习使用 |
| AI 服务商（OpenAI、Gemini 等） | 翻译 / 对话 | 由用户自行配置 API Key，各自适用其服务条款 |

## 许可证文本获取

- GNU Affero General Public License v3.0：<https://www.gnu.org/licenses/agpl-3.0.txt>
- GNU Lesser General Public License v3.0：<https://www.gnu.org/licenses/lgpl-3.0.txt>
- 上游 MIT 许可证：见 [`LICENSES/upstream-smoothie-reader-MIT.txt`](LICENSES/upstream-smoothie-reader-MIT.txt)
- 其余 MIT / Apache-2.0 / BSD-3-Clause / MIT-CMU：请参见各上游仓库的 `LICENSE` 文件。

> 说明：`assets/` 下的预置电子书与 `books/`、`dict/*.db`、`.env`、`ai_config.json`、`server*.log` 等本地运行时产物不随源代码分发，且不应提交至仓库。
