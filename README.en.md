English | [简体中文](README.md)

# 🧊 FixedPDF

> "When technology is democratized by AI, aesthetics and human-centric design become the ultimate differentiators."

A locally deployed AI bilingual reader built for **English technical manuals** — register maps, chip datasheets, IP product guides and academic papers. Deeply customized from [Smoothie Reader](https://github.com/Golden0Voyager/smoothie-reader), adding PDF reading, bilingual translation, multimodal image input and local model support.

---

## ✨ Key Features

- **Layout-preserving PDF translation**: Detects real table cells; after translation, tables, formulas, pin diagrams and numbers stay aligned in place. Export the whole document as a Chinese PDF.
- **20+ AI providers, ready to use**: Configure visually in the web UI, including Ollama and local CLIs — no code changes needed.
- **Multimodal input + smart routing**: Paste or upload images; requests with images go to a vision model, text-only ones to your chosen text model.
- **Word lookup · Bilingual comparison · TTS**: ECDICT offline dictionary, three comparison modes (overlay / paragraph / reflow), and Edge-TTS.
- **Local-first, private by design**: Bring your own API key. No cloud dependency, your data stays on your machine.

## 📸 Demo

> Using AMD's *AXI Memory Mapped to PCI Express* datasheet (PG055, November 24, 2023) as an example. The highlight: **table structure, signal names and numbers stay true to the original document**.
>
> Source: [AMD PG055](https://docs.amd.com/r/en-US/pg055-axi-bridge-pcie-gen2). Copyright AMD; used here for demonstration only.

### 1. Layout-Preserving Translation (IP Facts)

Original on the left, translation on the right. Cell boundaries, row heights and right-column alignment are all preserved. Identifiers such as `AMD Zynq™ 7000 SoC`, `AXI4`, `Vivado` and `54646` are kept verbatim — only prose is translated.

| Original | Translated |
|----------|------------|
| ![Original: IP Facts](assets/demo-ip-facts-en.png) | ![Translated: IP Facts](assets/demo-ip-facts-zh.png) |

### 2. Signal Table Translation (Port Descriptions)

Signal tables are where generic translators usually fail — they translate the signal names themselves, or break the columns. Here `refclk`, `axi_aresetn`, `s_axi_awlen[7:0]` and their bit widths are preserved exactly; only the `I/O` descriptions are translated, with borders and alignment intact.

| Original | Translated |
|----------|------------|
| ![Original: Port Descriptions](assets/demo-port-desc-en.png) | ![Translated: Port Descriptions](assets/demo-port-desc-zh.png) |

### 3. AI Term Explanation ("Look Up")

Select a term and hit **Look Up** — the AI explains *what it is*, not just a literal translation. Below, `AXI Memory Mapped to PCI Express` is broken down into its protocol role, working principle and typical use cases.

![AI term explanation](assets/demo-ai-explain.png)

### 4. Reader Interface

TOC navigation on the left, document content in the middle, AI assistant panel on the right (with name breakdown, key-point analysis, and more). Supports bilingual comparison, word lookup, TTS and highlights.

![Reader interface](assets/demo-reader-ui.png)

## 🚀 Quick Start

This project uses [uv](https://docs.astral.sh/uv/) to manage the Python environment and dependencies.

### 1. Install uv
Ensure Python 3.10+ is available, then install `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Import a Book & Launch
```bash
# Import an EPUB e-book
uv run reader3.py your_book.epub

# Start the server
uv run server.py
```
Open your browser at: 👉 **http://localhost:8123**

### 3. Configure AI
Enter the reading interface, click **Settings** in the top-left corner, and configure your **AI Provider** and API Key (e.g., [get a free Gemini Key](https://aistudio.google.com/apikey)).

> [!TIP]
> **🚀 Easter Egg**: Anywhere on the page, enter **`↑ ↑ ↓ ↓ ← → ← → B A`** (Konami Code) to unlock the hidden **Advanced AI Routing Panel**.

## 🛡️ Privacy
- **Local First**: No data leaves your device unless you explicitly trigger an AI or TTS request.
- **No Account Required**: Your data is stored only in your browser's `localStorage`.

## 📚 User Guide
For detailed configuration (offline dictionaries, multi-device access, port settings), see the [User Guide](docs/GUIDE.md).

## 📄 License
[GNU AGPL-3.0 License](LICENSE)

> This project is distributed under AGPL-3.0 because it integrates [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for third-party notices.
