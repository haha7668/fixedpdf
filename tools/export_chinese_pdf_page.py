"""Export one PDF page with its English text replaced by Chinese translations.

The original vector artwork, tables, and circuit diagram remain in place.  Text
blocks are painted white and redrawn in Chinese at their original coordinates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


CHINESE_FONT = Path(r"C:\Windows\Fonts\simhei.ttf")


PAGE_ONE_TRANSLATIONS = {
    "1:0": "MM54HC34/MM74HC34 非反相器",
    "1:1": "1988年1月",
    "1:2": "MM54HC34/MM74HC34 非反相器",
    "1:3": (
        "概述\nMM54HC34/MM74HC34 是采用先进硅栅 CMOS 技术制造的逻辑器件，"
        "具有 CMOS 固有的低静态功耗和宽电源电压范围等优点；其功能和引脚排列与"
        "标准 DM54LS/74LS 器件兼容。MM54HC34/MM74HC34 具有低功耗、"
    ),
    "1:4": "高速开关特性。所有输入端均通过内部二极管连接到 VCC 和地，以防止静电放电。",
    "1:5": "特性",
    "1:6": "Y 高速开关：tPLH、tPHL = 10 ns（典型值）",
    "1:7": "Y 高扇出：可驱动 10 个 LS 负载",
    "1:8": "连接图",
    "1:9": "双列直插式封装",
    "1:10": "TL/F/9389–1\n顶视图",
    "1:11": "订购型号 MM54HC34 或 MM74HC34",
    "1:12": "©1995 美国国家半导体公司\nRRD-B30M105/美国印刷",
    "1:13": "TL/F/9389",
}


def extract_blocks(page: pymupdf.Page) -> list[dict[str, object]]:
    blocks = []
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
        source = (text or "").strip()
        if len(source) >= 2:
            blocks.append({"rect": pymupdf.Rect(x0, y0, x1, y1), "source": source})
    return sorted(blocks, key=lambda block: block["rect"].y0)


def insert_box(page: pymupdf.Page, rect: pymupdf.Rect, text: str) -> bool:
    """Draw text using the largest CJK font size that fits in the source box."""
    inner = pymupdf.Rect(rect.x0 + 1.2, rect.y0 + 0.6, rect.x1 - 1.2, rect.y1 - 0.4)
    size = min(10.5, max(5.5, inner.height * 0.72))
    while size >= 4.5:
        result = page.insert_textbox(
            inner,
            text,
            fontname="pdf_reader_chinese",
            fontfile=str(CHINESE_FONT),
            fontsize=size,
            lineheight=1.05,
            color=(0, 0, 0),
            overlay=True,
        )
        if result >= 0:
            return True
        size -= 0.5
    return False


def insert_vertical(page: pymupdf.Page, rect: pymupdf.Rect, text: str) -> None:
    """Replace a narrow vertical title while retaining its original orientation."""
    page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_text(
        (rect.x0 + 1, rect.y1 - 1),
        text,
        fontname="pdf_reader_chinese",
        fontfile=str(CHINESE_FONT),
        fontsize=min(9, max(5, rect.width * 0.7)),
        color=(0, 0, 0),
        rotate=90,
        overlay=True,
    )


def replace_text(page: pymupdf.Page, blocks: list[dict[str, object]], translations: dict[str, str], page_number: int) -> None:
    for index, block in enumerate(blocks):
        text = translations.get(f"{page_number}:{index}")
        rect = block["rect"]
        if not text:
            continue

        if rect.height > rect.width * 3:
            insert_vertical(page, rect, text)
            continue
        # Preserve tiny circuit labels: they are part of the diagram, not prose.
        if rect.width < 20 or rect.height < 6:
            continue

        page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
        insert_box(page, rect, text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="source PDF")
    parser.add_argument("cache", type=Path, help="segment_cache.json for the book")
    parser.add_argument("output", type=Path, help="generated Chinese PDF")
    parser.add_argument("--page", type=int, default=1, help="1-based page number (default: 1)")
    parser.add_argument("--preview", type=Path, help="optional PNG preview path")
    parser.add_argument("--update-cache", action="store_true", help="repair page-one translations in the cache")
    args = parser.parse_args()

    cache = json.loads(args.cache.read_text(encoding="utf-8"))
    if args.page == 1:
        cache.update(PAGE_ONE_TRANSLATIONS)
        if args.update_cache:
            args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    document = pymupdf.open(args.source)
    try:
        page = document[args.page - 1]
        blocks = extract_blocks(page)
        replace_text(page, blocks, cache, args.page)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            args.output.unlink()
        document.save(args.output, garbage=4, deflate=True)

        if args.preview:
            args.preview.parent.mkdir(parents=True, exist_ok=True)
            if args.preview.exists():
                args.preview.unlink()
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            pixmap.save(args.preview)
    finally:
        document.close()


if __name__ == "__main__":
    main()
