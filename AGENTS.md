# Repository Guidelines

[简体中文版](AGENTS.zh-CN.md)

## Project Structure & Module Organization

The application is intentionally compact. `server.py` defines the FastAPI service, API routes, AI-provider integrations, TTS, and library management. `reader3.py` parses EPUB files into the internal book model (using the standard library, no EbookLib). `pdf_translation.py` implements structured, layout-preserving PDF translation. Browser UI code lives in the self-contained files under `templates/`; keep the HTML, CSS, and JavaScript for each page together. Tests are in `tests/test_server.py`, `tests/test_reader3.py`, and `tests/test_pdf_translation.py`. Documentation sources belong in `docs/`, utility scripts in `tools/`, and screenshots or sample media in `assets/`. Runtime books, caches, dictionaries, and generated `*_data/` directories are local artifacts and must not be committed.

## Build, Test, and Development Commands

Use Python 3.10 or newer and the `uv` package manager.

```bash
uv sync --dev                         # install locked runtime and development dependencies
uv run server.py                      # serve locally at http://127.0.0.1:8123
uv run reader3.py path/to/book.epub   # parse an EPUB from the command line
uv run pytest tests/                  # run the complete test suite
uv run pytest --cov --cov-report=term-missing tests/  # test with coverage
uv run ruff check server.py reader3.py tests/         # lint imports and Python code
uv run mypy server.py reader3.py      # run static type checks
```

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for constants. Add type hints to new public functions and keep route handlers focused. Ruff targets Python 3.12, enforces a 120-character line length, and checks pycodestyle, imports, naming, modernization, and common bug patterns. Preserve the single-file structure of each frontend template unless the architecture is deliberately changed.

## Testing Guidelines

Tests use `pytest`, `pytest-asyncio`, FastAPI's `TestClient`, fixtures, and mocks. Name files `test_*.py`, classes `TestFeature`, and functions `test_behavior`. Add regression tests for parser changes, routes, caching, and filesystem handling. Coverage is measured across `server`, `reader3`, and `pdf_translation`; the configured minimum is 75%.

## Commit & Pull Request Guidelines

History currently contains only an `init` commit, so no established message convention exists. Use concise, imperative subjects such as `Add EPUB cover fallback`. Keep commits focused. Pull requests should explain the behavior change, list verification commands, link relevant issues, and include screenshots for changes under `templates/`.

## Security & Configuration

Copy `.env.example` to `.env` for local configuration. Never commit `.env`, `ai_config.json`, API keys, imported books, `dict/*.db`, caches, or logs. Treat uploaded EPUB/PDF content and filenames as untrusted input.
