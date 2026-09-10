"""Convert docs/*.md to styled PDFs in package/ via HTML + Playwright (Chromium)."""
import os

import markdown
from playwright.sync_api import sync_playwright

# docs/ 下需要导出 PDF 的文件列表
MD_FILES = ['INTRODUCTION.md', 'GUIDE.md']


def md_to_html(md_path):
    with open(md_path) as f:
        md_text = f.read()

    body = markdown.markdown(md_text, extensions=['tables', 'fenced_code'])

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
@page {{
    size: A4;
    margin: 28mm 25mm 22mm 25mm;
}}

body {{
    font-family: -apple-system, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.8;
    color: #1C1B1F;
    -webkit-font-smoothing: antialiased;
}}

h1 {{
    font-size: 22pt;
    font-weight: 700;
    color: #6750A4;
    text-align: center;
    margin-top: 12mm;
    margin-bottom: 2mm;
    letter-spacing: 0.02em;
}}

h2 {{
    font-size: 14pt;
    font-weight: 700;
    color: #6750A4;
    margin-top: 16pt;
    margin-bottom: 6pt;
    padding-bottom: 4pt;
    border-bottom: 1.5px solid #E8E0F0;
}}

h3 {{
    font-size: 12pt;
    font-weight: 700;
    color: #333;
    margin-top: 14pt;
    margin-bottom: 5pt;
}}

p {{
    margin: 0 0 8pt 0;
    text-align: justify;
}}

/* Subtitle (first bold paragraph) */
h1 + p {{
    text-align: center;
    color: #666;
    font-size: 10pt;
    margin-bottom: 14pt;
}}

hr {{
    border: none;
    border-top: 0.5px solid #DDD;
    margin: 12pt 0;
}}

ul {{
    margin: 4pt 0 8pt 0;
    padding-left: 18pt;
}}

li {{
    margin-bottom: 3pt;
}}

/* Nested list */
li > ul {{
    margin-top: 2pt;
    margin-bottom: 2pt;
}}

strong {{
    font-weight: 700;
    color: #1a1a1a;
}}

code {{
    font-family: "SF Mono", "Menlo", "Monaco", monospace;
    font-size: 9pt;
    color: #6750A4;
    background: #F3EDF7;
    padding: 1px 4px;
    border-radius: 3px;
}}

pre {{
    background: #F3EDF7;
    padding: 10pt 14pt;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 8.5pt;
    line-height: 1.5;
}}

pre code {{
    background: none;
    padding: 0;
}}

a {{
    color: #6750A4;
    text-decoration: none;
}}

/* Tables */
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 8pt 0 12pt 0;
    font-size: 9.5pt;
}}

thead th {{
    background: #6750A4;
    color: white;
    font-weight: 600;
    padding: 7pt 10pt;
    text-align: left;
}}

tbody td {{
    padding: 6pt 10pt;
    border-bottom: 0.5px solid #DDD;
}}

tbody tr:nth-child(even) {{
    background: #F9F6FD;
}}

/* Avoid page breaks inside items */
li, tr {{
    break-inside: avoid;
}}

h2, h3 {{
    break-after: avoid;
}}

/* Blockquotes (for tips/notes) */
blockquote {{
    border-left: 3px solid #6750A4;
    margin: 8pt 0;
    padding: 4pt 12pt;
    color: #555;
    background: #F9F6FD;
    border-radius: 0 4px 4px 0;
}}
</style>
</head>
<body>
{body}
</body>
</html>'''


def convert_one(browser, md_path, pdf_path):
    html_content = md_to_html(md_path)
    page = browser.new_page()
    page.set_content(html_content, wait_until='networkidle')
    page.pdf(
        path=pdf_path,
        format='A4',
        margin={'top': '28mm', 'right': '25mm', 'bottom': '22mm', 'left': '25mm'},
        display_header_footer=True,
        header_template='<span></span>',
        footer_template='<div style="width:100%;text-align:center;font-size:9px;color:#999;font-family:sans-serif"><span class="pageNumber"></span></div>',
        print_background=True,
    )
    page.close()
    size_kb = os.path.getsize(pdf_path) / 1024
    print(f'  {os.path.basename(pdf_path)} ({size_kb:.0f} KB)')


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    docs_dir = os.path.join(root, 'docs')
    pkg_dir = os.path.join(root, 'package')

    print('Generating PDFs...')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for md_name in MD_FILES:
            md_path = os.path.join(docs_dir, md_name)
            pdf_name = os.path.splitext(md_name)[0] + '.pdf'
            pdf_path = os.path.join(pkg_dir, pdf_name)
            if not os.path.exists(md_path):
                print(f'  [skip] {md_name} not found')
                continue
            convert_one(browser, md_path, pdf_path)
        browser.close()
    print('Done.')


if __name__ == '__main__':
    main()
