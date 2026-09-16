# Third-Party Notices

本项目（Reader3 / Smoothie Reader 定制版）集成并分发以下第三方组件。根据各组件的许可证要求（AGPL-3.0、LGPL-3.0 及各类宽松许可证均要求在分发时附上版权与许可声明），在此逐项列出其版权归属与许可证。

## Copyleft 依赖（对本仓库许可证有约束）

| 组件 | 许可证 | 版权方 | 说明 |
|------|--------|--------|------|
| PyMuPDF / MuPDF | GNU AGPL-3.0 或 Artifex 商业许可 | Artifex Software, Inc. | PDF 解析、文本/段落/坐标提取、排字 |
| edge-tts | LGPL-3.0（`src/edge_tts/srt_composer.py` 为 MIT） | rany2 及贡献者 | 文本朗读（TTS） |
| PyInstaller | GPL-2.0-or-later WITH Bootloader-exception | PyInstaller Development Team | 打包工具（Bootloader 例外允许打包闭源应用） |

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
| lxml | BSD-3-Clause | lxml developers |
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
| ECDICT 词典数据 | MIT | skywind3000（ECDICT 项目） |

## 许可证文本获取

- GNU Affero General Public License v3.0：<https://www.gnu.org/licenses/agpl-3.0.txt>
- GNU Lesser General Public License v3.0：<https://www.gnu.org/licenses/lgpl-3.0.txt>
- GNU General Public License v2.0（含 Bootloader-exception）：<https://pyinstaller.org/en/stable/license.html>
- MIT / Apache-2.0 / BSD-3-Clause / MIT-CMU：请参见各上游仓库的 `LICENSE` 文件。

> 说明：`assets/` 下的预置电子书与 `books/`、`dict/*.db`、`.env`、`ai_config.json`、`server*.log` 等本地运行时产物不随源代码分发，且不应提交至仓库。
