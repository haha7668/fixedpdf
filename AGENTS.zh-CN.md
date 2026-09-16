# 仓库贡献指南

[English version](AGENTS.md)

## 项目结构与模块组织

项目采用紧凑结构。`server.py` 包含 FastAPI 服务、API 路由、AI 服务商集成、TTS 和书库管理；`reader3.py` 负责将 EPUB 解析为内部书籍模型（使用标准库，不依赖 EbookLib）；`pdf_translation.py` 实现保留版式的结构化 PDF 翻译。浏览器界面位于 `templates/`，每个页面的 HTML、CSS 和 JavaScript 保持在同一文件中。测试位于 `tests/test_server.py`、`tests/test_reader3.py` 和 `tests/test_pdf_translation.py`。文档源文件、工具脚本和示例资源分别放在 `docs/`、`tools/` 和 `assets/`。运行时书籍、缓存、词典及 `*_data/` 目录不得提交。

## 构建、测试与开发命令

使用 Python 3.10 或更高版本，并通过 `uv` 管理环境。

```bash
uv sync --dev                         # 安装锁定的运行及开发依赖
uv run server.py                      # 在 http://127.0.0.1:8123 启动服务
uv run reader3.py path/to/book.epub   # 从命令行解析 EPUB
uv run pytest tests/                  # 运行完整测试套件
uv run pytest --cov --cov-report=term-missing tests/  # 测试并显示覆盖率
uv run ruff check server.py reader3.py tests/         # 检查代码和导入
uv run mypy server.py reader3.py      # 执行静态类型检查
```

## 编码风格与命名约定

Python 使用四空格缩进；函数和变量采用 `snake_case`，类采用 `PascalCase`，常量使用全大写。为新增的公共函数添加类型标注，并保持路由处理函数职责单一。Ruff 以 Python 3.12 为目标版本，行宽为 120 字符。除非明确调整架构，否则保留前端模板的单文件组织方式。

## 测试规范

测试使用 `pytest`、`pytest-asyncio`、FastAPI `TestClient`、fixtures 和 mocks。测试文件命名为 `test_*.py`，测试类使用 `TestFeature`，测试函数使用 `test_behavior`。解析器、路由、缓存或文件系统行为变更都应添加回归测试。`server`、`reader3` 和 `pdf_translation` 的最低覆盖率要求为 75%。

## 提交与拉取请求规范

当前历史仅有一个 `init` 提交，尚无固定格式。提交标题应简洁并使用祈使语气，例如 `Add EPUB cover fallback`，每个提交只处理一个主题。拉取请求需说明行为变化、列出验证命令并关联相关 issue；修改 `templates/` 时应附界面截图。

## 安全与配置

将 `.env.example` 复制为 `.env` 进行本地配置。禁止提交 `.env`、`ai_config.json`、API 密钥、导入书籍、`dict/*.db`、缓存或日志。所有上传的 EPUB/PDF 内容和文件名均应视为不可信输入。
