"""Export page 2 as a Chinese PDF without changing the data-sheet layout."""

from __future__ import annotations

import os
from pathlib import Path

import pymupdf


FONT_FILE = Path(r"C:\Windows\Fonts\simhei.ttf")
SOURCE_PDF = Path(os.environ["LOCALAPPDATA"]) / "pdf_reader" / "books" / "MM54HC34MM74HC34 Non-Inverter_data" / "book.pdf"
OUTPUT_PDF = Path("output/pdf/MM54HC34MM74HC34_中文第2页_保留版式.pdf")
OUTPUT_PREVIEW = Path("output/pdf/MM54HC34MM74HC34_中文第2页_保留版式.png")


LINE_TRANSLATIONS = {
    "Absolute Maximum Ratings (Notes 1 & 2)": "绝对最大额定值（注1和注2）",
    "Supply Voltage (VCC)": "电源电压（VCC）",
    "DC Input Voltage (VIN)": "直流输入电压（VIN）",
    "DC Output Voltage (VOUT)": "直流输出电压（VOUT）",
    "Clamp Diode Current (IIK, IOK)": "钳位二极管电流（IIK、IOK）",
    "DC Output Current, per pin (IOUT)": "每引脚直流输出电流（IOUT）",
    "DC VCC or GND Current, per pin (IICC)": "每引脚直流 VCC 或 GND 电流（IICC）",
    "Storage Temperature Range (TSTG)": "存储温度范围（TSTG）",
    "Power Dissipation (PD)": "功耗（PD）",
    "(Note 3)": "（注3）",
    "S.O. Package only": "仅限 S.O. 封装",
    "Lead Temperature (TL)": "引脚温度（TL）",
    "(Soldering 10 seconds)": "（焊接10秒）",
    "Operating Conditions": "工作条件",
    "Min": "最小值",
    "Max": "最大值",
    "Units": "单位",
    "DC Input or Output Voltage": "直流输入或输出电压",
    "Operating Temp. Range (TA)": "工作温度范围（TA）",
    "Input Rise or Fall Times": "输入上升或下降时间",
    "DC Electrical Characteristics (Note 4)": "直流电气特性（注4）",
    "Symbol": "符号",
    "Parameter": "参数",
    "Conditions": "条件",
    "Typ": "典型值",
    "Guaranteed Limits": "保证限值",
    "Minimum High Level": "最小高电平",
    "Maximum Low Level": "最大低电平",
    "Input Voltage": "输入电压",
    "Input Voltage**": "输入电压**",
    "Output Voltage": "输出电压",
    "Maximum Input": "最大输入",
    "Current": "电流",
    "Maximum Quiescent": "最大静态",
    "Supply Current": "电源电流",
}


def draw_replacement(page: pymupdf.Page, rect: pymupdf.Rect, text: str, *, minimum: float = 3.2) -> None:
    """Cover one source text rectangle and redraw concise Chinese inside it."""
    page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
    inner = pymupdf.Rect(rect.x0 + 0.3, rect.y0 + 0.1, rect.x1 - 0.2, rect.y1 - 0.1)
    size = min(9.0, max(minimum, inner.height * 0.92))
    while size >= minimum:
        remainder = page.insert_textbox(
            inner,
            text,
            fontname="pdf_reader_chinese",
            fontfile=str(FONT_FILE),
            fontsize=size,
            lineheight=1.0,
            color=(0, 0, 0),
            overlay=True,
        )
        if remainder >= 0:
            return
        size -= 0.25


def replace_line_labels(page: pymupdf.Page) -> None:
    """Replace only labels; numerical cells, formulae and units are untouched."""
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            source = "".join(span["text"] for span in line.get("spans", [])).strip()
            target = LINE_TRANSLATIONS.get(source)
            if target:
                draw_replacement(page, pymupdf.Rect(line["bbox"]), target)


def replace_grouped_prose(page: pymupdf.Page) -> None:
    """Replace text which the source PDF split into multiple word spans."""
    groups = [
        ((70.7, 94.2, 256.0, 101.2), "如需军用/航空航天指定器件，"),
        ((70.7, 102.7, 256.0, 109.6), "请联系国家半导体销售部门，"),
        ((70.7, 111.1, 249.4, 118.1), "通过办事处/分销商获取供货与规格信息。"),
        ((70.7, 562.9, 321.4, 568.4), "注1：绝对最大额定值是可能导致器件损坏的极限值。"),
        ((70.7, 571.9, 251.9, 577.4), "注2：除非另有说明，所有电压均以地为参考。"),
        ((70.7, 579.4, 465.1, 587.1), "注3：功耗温度降额：塑料 N 封装在 65°C 至 85°C 为 -12 mW/°C；陶瓷 J 封装在 100°C 至 125°C 为 -12 mW/°C。"),
        ((70.8, 589.2, 465.2, 610.3), "注4：5 V ±10% 电源下，HC 的最坏 VOH、VOL 值出现在 4.5 V；VIH、VIL 分别出现在 VCC=5.5 V、4.5 V。CMOS 最坏漏电流出现在较高电压，应采用 6.0 V 数值。"),
        ((70.7, 612.8, 405.1, 619.4), "**VIL 限值当前按 VCC 的 20% 测试；上述 30% VCC 规范最迟于 1989 年第一季度实施。"),
    ]
    for coordinates, text in groups:
        draw_replacement(page, pymupdf.Rect(coordinates), text, minimum=2.6)


def main() -> None:
    if not SOURCE_PDF.exists():
        raise FileNotFoundError(SOURCE_PDF)
    if not FONT_FILE.exists():
        raise FileNotFoundError(FONT_FILE)

    source = pymupdf.open(SOURCE_PDF)
    output = pymupdf.open()
    try:
        source_page = source[1]
        page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
        page.show_pdf_page(page.rect, source, 1)
        replace_line_labels(page)
        replace_grouped_prose(page)

        OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
        output.save(OUTPUT_PDF, garbage=4, deflate=True)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        pixmap.save(OUTPUT_PREVIEW)
    finally:
        output.close()
        source.close()


if __name__ == "__main__":
    main()
