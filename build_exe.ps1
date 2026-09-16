$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed. Install it from https://docs.astral.sh/uv/ and retry."
}

uv sync --dev
uv run pyinstaller --noconfirm --clean --onedir --windowed `
    --name pdf_reader `
    --add-data "templates;templates" `
    --add-data "assets;assets" `
    --collect-all edge_tts `
    --collect-all google.genai `
    --collect-all fitz `
    --collect-all pymupdf `
    launcher.py

Write-Host "Built: dist\pdf_reader\pdf_reader.exe"
