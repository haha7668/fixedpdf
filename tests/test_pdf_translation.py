import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

import pdf_translation as translation
import server


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / 'sample'
    folder.mkdir()
    path = folder / 'book.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        for y in (50, 80, 110):
            page.draw_line((30, y), (370, y))
        for x in (30, 100, 370):
            page.draw_line((x, 50), (x, 110))
        page.insert_text((35, 69), 'Code', fontsize=10)
        page.insert_text((110, 69), 'Description', fontsize=10)
        page.insert_text((35, 99), '7.25', fontsize=10)
        page.insert_text((110, 99), 'Supply voltage VCC = 5 V', fontsize=10)
        page.insert_text((35, 160), 'GND', fontsize=10)
        doc.save(path)
    return path


def test_native_cells_not_flattened(source):
    plan = translation.analyze_page(str(source), 1)
    assert [(t['rows'], t['cols']) for t in plan['tables']] == [(2, 2)]
    assert {r['id'] for r in plan['regions']} == {'t0r0c0', 't0r0c1', 't0r1c1'}
    assert next(r for r in plan['regions'] if r['id'] == 't0r1c1')['bbox'][0] > 100


def test_render_preserves_rules_numbers_and_signals(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    output = tmp_path / 'translated.pdf'
    report = translation.render_page(str(source), plan, {
        't0r0c0': '编号', 't0r0c1': '说明', 't0r1c1': '电源电压 VCC = 5 V'}, str(output))
    assert report['translated'] == 3
    with fitz.open(source) as before, fitz.open(output) as after:
        assert len(before[0].get_drawings()) == len(after[0].get_drawings())
        text = after[0].get_text()
        assert '7.25' in text and 'GND' in text and 'VCC = 5 V' in text
        assert 'Description' not in text
        assert '说明' in text.replace(' ', '')
        assert before[0].rect == after[0].rect


def test_unfit_translation_keeps_original(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    output = tmp_path / 'fallback.pdf'
    report = translation.render_page(str(source), plan, {'t0r0c0': '完整内容' * 100}, str(output))
    assert report['translated'] == 0
    assert report['warnings']
    with fitz.open(output) as doc:
        assert 'Code' in doc[0].get_text()


def test_dense_footnote_has_no_hidden_html_margin(tmp_path):
    path, output = tmp_path / 'footnote.pdf', tmp_path / 'footnote-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 300), 'Note 4:', fontsize=5.5)
        page.insert_text((65, 300), 'VCC = 5 V', fontsize=5.5)
        span = page.get_text('dict')['blocks'][0]['lines'][0]['spans'][0]
        doc.save(path)
    region = translation._region('note', [span], (40, 294, 60, 300.5), 'cell')
    plan = {'page': 1, 'regions': [region], 'tables': [], 'warnings': []}
    report = translation.render_page(str(path), plan, {'note': '注 4：'}, str(output))
    assert report['translated'] == 1 and not report['warnings']
    with fitz.open(output) as doc, fitz.open(path) as original:
        assert 'Note' not in doc[0].get_text()
        assert '注4：' in doc[0].get_text().replace(' ', '')
        assert doc[0].search_for('VCC')[0] == original[0].search_for('VCC')[0]
        sizes = [s['size'] for b in doc[0].get_text('dict')['blocks']
                 for line in b.get('lines', []) for s in line['spans'] if '注' in s['text']]
        assert sizes and min(sizes) >= 5.49


def test_tight_multiline_prose_merges_before_collision_check(tmp_path):
    path, output = tmp_path / 'tight.pdf', tmp_path / 'tight-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=360, height=240)
        page.insert_text((40, 100), 'First technical sentence overlaps', fontsize=10)
        page.insert_text((40, 110), 'Second technical sentence below', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['regions']) == 1
    assert plan['regions'][0]['source'] == 'First technical sentence overlaps\nSecond technical sentence below'
    report = translation.render_page(
        str(path), plan, {plan['regions'][0]['id']: '第一行技术说明\n第二行技术说明'}, str(output))
    assert report['translated'] == 1
    assert not report['warnings']
    with fitz.open(output) as doc:
        text = doc[0].get_text()
        assert 'First technical sentence' not in text
        assert '技术说明' in text.replace(' ', '')


def test_numbered_note_merges_into_one_region(tmp_path):
    """A note marker sits in a hanging indent; its lines still form one region."""
    path = tmp_path / 'note.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), '1.  For the supported versions of third-party tools, see the', fontsize=8)
        page.insert_text((52, 90), 'Vivado Design Suite User Guide: Release Notes, Installation,', fontsize=8)
        page.insert_text((52, 100), 'and Licensing.', fontsize=8)
        page.insert_text((40, 130), '2.  Standalone driver details can be found in the Vitis directory', fontsize=8)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    notes = [r for r in plan['regions'] if r['source'].startswith('1.')]
    assert len(notes) == 1
    assert notes[0]['source'].count('\n') == 2
    assert not any(r['source'].startswith('2.') and '\n' in r['source'] for r in plan['regions'])


def test_list_marker_opens_a_new_item_and_keeps_its_own_lines(tmp_path):
    """A bullet on its own line starts an item, and its wrap lines stay with it.

    The marker arrives as a separate text line here, so nothing inside the next
    line reveals that it begins an item rather than continuing the previous one.
    Item spacing matches normal leading, which is what makes the confusion real.
    """
    path = tmp_path / 'bullets.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=300)
        page.insert_text((30, 100), '\u2022', fontsize=10)
        page.insert_text((46, 100), 'Maximum Payload Size up to 256 bytes', fontsize=10)
        page.insert_text((46, 112), 'and legacy interrupt support', fontsize=10)
        page.insert_text((30, 124), '\u2022', fontsize=10)
        page.insert_text((46, 124), 'PCIe access to memory-mapped AXI4 space', fontsize=10)
        page.insert_text((46, 136), 'and a second wrapped line', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    first = [r for r in plan['regions'] if 'Maximum' in r['source']]
    second = [r for r in plan['regions'] if 'PCIe access' in r['source']]
    assert len(first) == 1 and len(second) == 1
    assert 'and legacy interrupt support' in first[0]['source']
    assert 'and a second wrapped line' in second[0]['source']
    assert 'PCIe access' not in first[0]['source']
    assert 'Maximum' not in second[0]['source']


def test_inline_list_marker_sets_body_offset():
    """A marker inside the text span must still move the alignment offset.

    Generators differ: some emit the bullet as its own span, others keep it in
    the text. Both must report where the body starts, or an item cannot merge
    with the lines that continue it.
    """
    def char(letter, x0, x1):
        return {'c': letter, 'bbox': (x0, 90, x1, 104)}

    separate = [
        {'text': '\u2022', 'bbox': (40, 90, 46, 104), 'size': 10, 'chars': [char('\u2022', 40, 46)]},
        {'text': 'Maximum', 'bbox': (49, 90, 140, 104), 'size': 10, 'chars': [char('M', 49, 58)]},
    ]
    assert translation._body_left(separate) == (49, True)

    inline = [{
        'text': '1.  For the supported', 'bbox': (40, 90, 200, 104), 'size': 8,
        'chars': [char('1', 40, 44), char('.', 44, 46), char(' ', 46, 48),
                  char(' ', 48, 50), char('F', 50, 56)],
    }]
    assert translation._body_left(inline) == (50, True)

    plain = [{'text': 'Introduction', 'bbox': (40, 90, 140, 104), 'size': 10,
              'chars': [char('I', 40, 46)]}]
    assert translation._body_left(plain) == (40, False)


def test_tight_leading_does_not_block_a_replaceable_region(tmp_path):
    """A glyph box spans the full line box, so leading alone must not refuse.

    Two paragraphs at 8 pt on 10 pt leading report overlapping boxes while the
    real ink is well separated: the descenders stay clear of the next line.
    Erasing the upper paragraph is safe, and the scratch-page probe must allow
    it instead of preserving the English text.
    """
    path, output = tmp_path / 'leading.pdf', tmp_path / 'leading-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=320)
        page.insert_text((40, 200), 'Upper paragraph of test text', fontsize=8)
        page.insert_text((60, 210), 'Lower separate paragraph', fontsize=8)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    upper = next(r for r in plan['regions'] if 'Upper' in r['source'])
    lower = next(r for r in plan['regions'] if 'Lower' in r['source'])
    # The reported boxes really do overlap, which is what used to refuse the
    # region; the two paragraphs are still separate regions (different indent).
    assert fitz.Rect(upper['ink'][0]).y1 > fitz.Rect(lower['ink'][0]).y0
    assert '\n' not in upper['source']
    # Only the upper paragraph is being replaced, so only its own ink is owned.
    owned = [fitz.Rect(i) for i in upper['ink']]
    assert translation._deletes_neighbour(str(path), 1, upper, owned) is False
    report = translation.render_page(str(path), plan, {upper['id']: '上半段测试文本'}, str(output))
    assert report['placement_count'] == 1
    assert not report['warnings']
    with fitz.open(output) as doc:
        text = doc[0].get_text()
        assert 'Upper paragraph' not in text
        assert 'Lower separate paragraph' in text
        assert '上半段测试文本' in text.replace(' ', '')


def test_scratch_probe_still_refuses_a_real_neighbour_collision(tmp_path):
    """Exactness must not become permissiveness: real clashes are still caught."""
    path, output = tmp_path / 'clash.pdf', tmp_path / 'clash-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=320)
        page.insert_text((40, 200), 'Upper paragraph of test text', fontsize=8)
        page.insert_text((40, 210), 'Lower separate paragraph', fontsize=18)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    upper = next(r for r in plan['regions'] if 'Upper' in r['source'])
    owned = [fitz.Rect(i) for i in upper['ink']]
    assert translation._deletes_neighbour(str(path), 1, upper, owned) is True
    report = translation.render_page(str(path), plan, {upper['id']: '上半段测试文本'}, str(output))
    assert report['placement_count'] == 0
    assert [w['code'] for w in report['warnings']] == ['adjacent_glyph']
    with fitz.open(output) as doc:
        assert 'Upper paragraph of test text' in doc[0].get_text()


def test_heading_keeps_attached_technical_identifier_line(tmp_path):
    path, output = tmp_path / 'heading.pdf', tmp_path / 'heading-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=300)
        page.insert_text((50, 70), 'AXI Memory Mapped', fontsize=24)
        page.insert_text((50, 94), 'to PCI Express', fontsize=24)
        page.insert_text((50, 118), 'Gen2 v2.9', fontsize=24)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['regions']) == 1
    assert plan['regions'][0]['source'] == 'AXI Memory Mapped\nto PCI Express\nGen2 v2.9'
    report = translation.render_page(
        str(path), plan, {plan['regions'][0]['id']: 'AXI内存映射至PCI Express\nGen2 v2.9'}, str(output))
    assert report['translated'] == 1
    assert not report['warnings']
    with fitz.open(output) as doc:
        text = doc[0].get_text()
        assert 'AXI Memory Mapped' not in text
        assert 'Gen2 v2.9' in text


def test_short_tail_is_translated_with_its_paragraph(tmp_path):
    path, output = tmp_path / 'tail.pdf', tmp_path / 'tail-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), 'The bridge supports pending memory mapped', fontsize=10)
        page.insert_text((40, 92), 'transactions.', fontsize=10)
        page.insert_text((40, 120), 'A separate paragraph below.', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    first = plan['regions'][0]
    assert first['source'].endswith('\ntransactions.')
    assert len(plan['regions']) == 2
    report = translation.render_page(str(path), plan, {first['id']: '桥支持待处理的内存映射事务。'}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']
    with fitz.open(output) as doc:
        assert 'transactions.' not in doc[0].get_text()
        assert 'A separate paragraph below.' in doc[0].get_text()


def test_heading_ink_aligns_with_the_source_first_character(tmp_path):
    """大标题首字符的墨迹要与原文对齐，不能看着像被缩进。

    汉字笔画在字身框内自带左边距，拉丁大写字母的边距小得多；同一盒左边缘下
    28 pt 的「目录」比「Table of Contents」右约 4 pt。排版时按首字符的边距之差
    左移补偿，使译文墨迹落在原文墨迹的位置。
    """
    assert translation._ink_bearing('目', 28) > translation._ink_bearing('T', 28)
    assert translation._left_shift('Table of Contents', '目录', 28) > 2
    assert translation._left_shift('LogiCORE IP Product Guide', 'LogiCORE IP 产品指南', 28) == 0
    # 首字符相同则无需补偿，避免把正常排版推歪。
    assert translation._left_shift('Standards', 'Standards', 21) == 0

    path, output = tmp_path / 'toc.pdf', tmp_path / 'toc-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=300)
        page.insert_text((54, 100), 'Table of Contents', fontsize=28)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    assert region['font_size'] >= 28
    report = translation.render_page(str(path), plan, {region['id']: '目录'}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']

    def ink_left(page, clip, scale=10):
        pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(scale, scale))
        width, height, n, samples = pix.width, pix.height, pix.n, pix.samples
        best = None
        for y in range(height):
            for x in range(width):
                if samples[(y * width + x) * n] < 160:
                    if best is None or x < best:
                        best = x
                    break
        return None if best is None else clip.x0 + best / scale

    clip = fitz.Rect(44, 60, 200, 115)
    with fitz.open(path) as before, fitz.open(output) as after:
        src_ink = ink_left(before[0], clip)
        out_ink = ink_left(after[0], clip)
    assert src_ink is not None and out_ink is not None
    assert abs(out_ink - src_ink) < 1.0, f'标题墨迹未对齐: 原文 {src_ink}, 译文 {out_ink}'


def test_small_text_is_not_shifted_by_bearing(tmp_path):
    """正文不做边距补偿：小字号差异本就很小，补偿反而可能推歪版面。"""
    path, output = tmp_path / 'body.pdf', tmp_path / 'body-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=200)
        page.insert_text((54, 100), 'Memory Map', fontsize=11)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    assert region['font_size'] < 14
    report = translation.render_page(str(path), plan, {region['id']: '内存映射'}, str(output))
    assert report['placement_count'] == 1
    with fitz.open(output) as doc:
        box = fitz.Rect(region['bbox'])
        lines = [line['bbox'] for block in doc[0].get_text('dict')['blocks']
                 for line in block.get('lines', [])
                 if ''.join(s['text'] for s in line['spans']).strip()]
    assert lines and lines[0][0] >= box.x0 - .5, '正文不应被左移'


def test_toc_entries_keep_their_own_lines(tmp_path):
    """目录的每个条目必须独占一行，不能把下一条目的行首折到上一行末尾。

    整段当作连续文本流排版时，行边界会被抹掉，于是「仿真设计概述」的头两个字
    被拉到上一行末尾。原文同样是多行、每行一次换行，逐行盒即可恢复该结构。
    """
    path, output = tmp_path / 'toc.pdf', tmp_path / 'toc-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=400)
        page.insert_text((108, 99), 'Overview . . . . . . . . . . . . . . . . . . . . .  84', fontsize=11)
        page.insert_text((108, 115), 'Simulation Design Overview . . . . . . . . .  84', fontsize=11)
        page.insert_text((108, 131), 'Implementation Design Overview . . . . . .  86', fontsize=11)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    assert len(region['lines']) == 3
    assert region['source'].count('\n') == 2
    report = translation.render_page(str(path), plan, {
        region['id']: '概述 . . . . . . . . . . . . . . . . . . . . .  84\n'
                      '仿真设计概述 . . . . . . . . . . . . . . .  84\n'
                      '实现设计概述 . . . . . . . . . . . . . . .  86'}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']
    with fitz.open(output) as doc:
        rows = [''.join(s['text'] for s in line['spans']).replace(' ', '')
                for block in doc[0].get_text('dict')['blocks']
                for line in block.get('lines', [])]
    # 三个条目各自成行：不能出现「…84仿真」或「…84实现」这类拼接。
    assert any(row.startswith('概述') for row in rows)
    assert any(row.startswith('仿真设计概述') for row in rows)
    assert any(row.startswith('实现设计概述') for row in rows)
    assert not any('84仿真' in row or '84实现' in row for row in rows)


def test_wrapped_translation_falls_back_to_flow_layout(tmp_path):
    """逐行盒放不下时退回整段排版，宁可重排也不放弃翻译。"""
    path, output = tmp_path / 'toc-wrap.pdf', tmp_path / 'toc-wrap-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=400)
        page.insert_text((108, 99), 'Overview . . . . . . . . .  84', fontsize=11)
        page.insert_text((108, 115), 'Support . . . . . . . . .  86', fontsize=11)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    # 单行盒放不下、整段两行放得下：应退回整段排版而不是判为放不下。
    left, top, right, bottom = region['bbox']
    assert translation._line_boxes(region, left, right, bottom) is not None
    report = translation.render_page(str(path), plan, {region['id']: '中' * 35}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']



    path, output = tmp_path / 'mark.pdf', tmp_path / 'mark-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), 'Compatible with AMBA', fontsize=10)
        end = 40 + fitz.get_text_length('Compatible with AMBA', fontsize=10)
        page.insert_text((end, 76), '\u00ae', fontsize=7)
        page.insert_text((end + 7, 80), ' AXI Protocol', fontsize=10)
        page.insert_text((40, 92), 'Specification.', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['regions']) == 1
    r = plan['regions'][0]
    assert 'Specification.' in r['source'] and '\u00ae' in r['source']
    masked, tokens = translation.protect(r['source'])
    assert '\u00ae' not in masked
    assert translation.restore(masked, tokens) == r['source']
    report = translation.render_page(str(path), plan, {r['id']: '兼容 AMBA\u00ae AXI 协议规范。'}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']
    with fitz.open(output) as doc:
        assert 'Compatible' not in doc[0].get_text()
        assert '\u00ae' in doc[0].get_text()


def test_note_label_space_survives_cjk_space_removal(tmp_path):
    """编号与中文之间的间隔不能被「去中英空格」规则吞掉。"""
    path, output = tmp_path / 'note-space.pdf', tmp_path / 'note-space-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=200)
        page.insert_text((108, 99), '1.  For the supported versions of tools', fontsize=11)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    report = translation.render_page(str(path), plan, {
        region['id']: '1. 有关支持的第三方工具版本'}, str(output))
    assert report['placement_count'] == 1
    with fitz.open(output) as doc:
        assert '1. 有关' in doc[0].get_text().replace('\u00a0', ' ')


def test_paragraphs_respect_columns_and_horizontal_rules(tmp_path):
    path = tmp_path / 'columns.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=300)
        for x, name in ((40, 'Left'), (330, 'Right')):
            page.insert_text((x, 80), name + ' column has a long description', fontsize=10)
            page.insert_text((x, 92), 'continued.', fontsize=10)
            page.draw_line((x, 95), (x + 200, 95))
            page.insert_text((x, 104), 'Separate label', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    descriptions = [r for r in plan['regions'] if 'description' in r['source']]
    assert len(descriptions) == 2
    assert all(r['source'].endswith('continued.') for r in descriptions)
    assert all('Separate' not in r['source'] for r in descriptions)
    assert all(not ('Left' in r['source'] and 'Right' in r['source']) for r in plan['regions'])


def test_superscript_stays_with_its_line_and_keeps_script_format(tmp_path):
    """上标必须随整行一起翻译排版，并保持上标格式。

    原文 ``range = 2ⁿ`` 的 ``n`` 是抬高基线的细小字形。若把它当作「混合基线
    公式」的证据，整行会被拆成碎片分头排版：正文重新排到左边，上标留在原
    坐标，两者之间裂开一大段空白（第 20 页实测 176 pt）。上标是正文的一部分，
    应并入整行翻译，并在成稿里仍是角标。
    """
    path, output = tmp_path / 'power.pdf', tmp_path / 'power-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=300)
        head = 'The range must be a contiguous power of two, such that the range = 2'
        page.insert_text((60, 100), head, fontsize=9)
        end = 60 + fitz.get_text_length(head, fontsize=9)
        page.insert_text((end, 96), 'n', fontsize=7)              # 上标 n
        page.insert_text((end + 5, 100), ' and the n least bits are zero.', fontsize=9)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    # 整行（含上标）只应形成一个区域，而不是被拆成多个碎片。
    assert len(plan['regions']) == 1, [(r['id'], r['source']) for r in plan['regions']]
    region = plan['regions'][0]
    assert translation.SCRIPT_OPEN in region['source']
    # 角标标记随整行保护与还原，模型不必理解它的结构。
    masked, tokens = translation.protect(region['source'])
    assert any(translation.SCRIPT_OPEN in value for value in tokens.values())
    assert translation.restore(masked, tokens) == region['source']
    # 渲染后仍是上标，不会降级成正文；正文与角标之间不再裂开空白。
    assert '<sup>n</sup>' in translation._translation_markup(region['source'])
    scripted = ('该范围必须是连续的二次幂，使得范围 = 2'
                + translation.SCRIPT_OPEN + 'n' + translation.SCRIPT_CLOSE + '且各位为零。')
    report = translation.render_page(str(path), plan, {region['id']: scripted}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']
    with fitz.open(output) as doc:
        rendered = doc[0].get_text()
    assert '2' in rendered and '且' in rendered.replace(' ', '')
    # 上标以更小的字号写出，不与正文同高。
    sizes = [span['size'] for block in fitz.open(output)[0].get_text('dict')['blocks']
             for line in block.get('lines', []) for span in line['spans'] if span['text'].strip()]
    assert min(sizes) < max(sizes) * .95, sizes


def test_script_span_detects_only_baseline_shifts():
    """只有真正偏离基线的细小字形才算角标。

    同基线的小字号（``V_CC`` 那种缩写）不是上标，不该被包成 ``<sup>``；
    商标符号另有处理，也不重复包裹。
    """
    def span(text, size, origin_y, x=100):
        return {'text': text, 'size': size, 'origin': (x, origin_y),
                'bbox': (x, origin_y - size, x + len(text) * 4, origin_y),
                'chars': [{'c': c, 'origin': (x, origin_y),
                           'bbox': (x, origin_y - size, x + 4, origin_y)} for c in text]}

    assert translation._script_span(span('n', 7.0, 96.0), 9.0, 100.0) is True       # 上标
    assert translation._script_span(span('i', 7.0, 103.0), 9.0, 100.0) is True      # 下标
    assert translation._script_span(span('CC', 7.0, 100.0), 9.0, 100.0) is False    # 同基线缩写
    assert translation._script_span(span('V', 9.0, 100.0), 9.0, 100.0) is False     # 正文
    assert translation._script_span(span('\u00ae', 6.0, 96.0), 9.0, 100.0) is False  # 商标符号


def test_formula_subscript_is_still_kept_native(tmp_path):
    """公式里的下标（V_CC）仍按原生文字保留，不并入译文。

    那类内容从解码字符串重建不可靠（自定义 Symbol 字体常把 '=' 解成 'e'），
    而且整行不是自然语言，不该当成可翻译的正文。
    """
    path, output = tmp_path / 'formula2.pdf', tmp_path / 'formula2-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 80), 'Voltage', fontsize=10)
        page.insert_text((85, 80), 'V', fontsize=10)
        page.insert_text((92, 83), 'CC', fontsize=7)
        page.insert_text((105, 80), '= 5 V', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert all('CC' not in r['source'] for r in plan['regions'])
    assert all(translation.SCRIPT_OPEN not in r['source'] for r in plan['regions'])
    report = translation.render_page(str(path), plan,
                                     {r['id']: '电压' for r in plan['regions']}, str(output))
    # 原生下标 CC 必须留在页面上，且译文不得把它吞掉。
    with fitz.open(path) as before, fitz.open(output) as after:
        assert after[0].search_for('CC') == before[0].search_for('CC') != []
    assert report['placement_count'] == len(plan['regions'])


def test_real_subscript_is_not_folded_into_prose(tmp_path):
    path, output = tmp_path / 'formula.pdf', tmp_path / 'formula-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 80), 'Voltage', fontsize=10)
        page.insert_text((85, 80), 'V', fontsize=10)
        page.insert_text((92, 83), 'CC', fontsize=7)
        page.insert_text((105, 80), '= 5 V', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert all('CC' not in r['source'] for r in plan['regions'])
    translation.render_page(str(path), plan, {r['id']: '电压' for r in plan['regions']}, str(output))
    with fitz.open(path) as before, fitz.open(output) as after:
        assert before[0].search_for('CC') == after[0].search_for('CC')


def test_signal_column_is_preserved_not_reported_as_missing_translation(tmp_path):
    path, output = tmp_path / 'ports.pdf', tmp_path / 'ports-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=200)
        for x in (20, 170, 380):
            page.draw_line((x, 20), (x, 100))
        for y in (20, 60, 100):
            page.draw_line((20, y), (380, y))
        for point, text in [((25, 40), 'Signal Name'), ((175, 40), 'Description'),
                            ((25, 80), 'refclk'), ((175, 80), 'Reference clock')]:
            page.insert_text(point, text, fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['regions']) == 3
    assert all(r['source'] != 'refclk' for r in plan['regions'])
    report = translation.render_page(str(path), plan, {r['id']: '说明' for r in plan['regions']}, str(output))
    assert report['pending_count'] == 0 and report['translation_count'] == 3
    with fitz.open(path) as before, fitz.open(output) as after:
        assert before[0].search_for('refclk') == after[0].search_for('refclk')


def test_unplaced_translation_remains_accessible_and_pending_is_separate(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    targets = {'t0r0c0': '完整内容' * 100, 't0r0c1': '说明'}
    report = translation.render_page(str(source), plan, targets, str(tmp_path / 'partial.pdf'))
    assert (report['translation_count'], report['placement_count'], report['pending_count']) == (2, 1, 1)
    assert report['unplaced_count'] == 1
    details = {d['id']: d for d in report['details']}
    assert details['t0r0c0']['translation'] == targets['t0r0c0']
    assert details['t0r0c0']['status'] == 'unplaced'
    assert details['t0r0c1']['status'] == 'placed'
    assert details['t0r1c1']['status'] == 'pending'


def test_deferred_cell_is_translated_without_erasing_uncertain_content(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    plan['regions'][0]['placement'] = 'deferred'
    r = plan['regions'][0]
    report = translation.render_page(str(source), plan, {r['id']: '编号'}, str(tmp_path / 'deferred.pdf'))
    assert report['translation_count'] == 1 and report['placement_count'] == 0
    assert report['details'][0]['translation'] == '编号'
    with fitz.open(tmp_path / 'deferred.pdf') as doc:
        assert 'Code' in doc[0].get_text()


@pytest.mark.asyncio
async def test_measured_overflow_retries_only_failed_regions(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    targets = {'t0r0c0': '完整内容' * 100, 't0r0c1': '说明'}
    async def answer(prompt, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        assert [r['id'] for r in payload['items']] == ['t0r0c0']
        assert payload['items'][0]['fit_feedback']['previous_translation'] == targets['t0r0c0']
        return '{"t0r0c0":"编号"}', 'mock'
    complete = AsyncMock(side_effect=answer)
    report, updated = await translation.render_with_fit_retry(
        str(source), plan, targets, str(tmp_path / 'fitted.pdf'), complete)
    assert report['translated'] == 2 and not report['warnings']
    assert updated == {'t0r0c0': '编号', 't0r0c1': '说明'}
    assert complete.await_count == 1
    assert targets['t0r0c0'] == '完整内容' * 100  # Caller input is not mutated.


@pytest.mark.asyncio
async def test_fit_retry_rejects_changed_numbers(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    targets = {'t0r1c1': '电源电压 VCC = 5 V ' + '完整内容' * 100}
    # Looks short enough but replaces the protected 5 with 6.
    complete = AsyncMock(return_value=('{"t0r1c1":"电源电压 __KEEP0__ = 6 V"}', 'mock'))
    report, updated = await translation.render_with_fit_retry(
        str(source), plan, targets, str(tmp_path / 'invalid.pdf'), complete)
    assert report['translated'] == 0 and report['warnings'][0]['code'] == 'text_does_not_fit'
    assert updated == targets and complete.await_count == 2


@pytest.mark.asyncio
async def test_fit_retry_is_bounded(source, tmp_path):
    plan = translation.analyze_page(str(source), 1)
    complete = AsyncMock(side_effect=[(json.dumps({'t0r0c0': '过长译文' * i}), 'mock') for i in (99, 98)])
    report, _ = await translation.render_with_fit_retry(
        str(source), plan, {'t0r0c0': '完整内容' * 100}, str(tmp_path / 'bounded.pdf'), complete)
    assert report['translated'] == 0 and complete.await_count == 2


@pytest.mark.asyncio
async def test_successful_page_never_requests_fit_retry(source, tmp_path):
    complete = AsyncMock()
    plan = translation.analyze_page(str(source), 1)
    report, _ = await translation.render_with_fit_retry(
        str(source), plan, {'t0r0c0': '编号'}, str(tmp_path / 'ready.pdf'), complete)
    assert report['translated'] == 1
    complete.assert_not_called()


def test_english_number_words_may_become_digits():
    """英文数词写成阿拉伯数字是正常翻译，不该被判成篡改数值。

    源文 ``a one in any location`` 译作「任意位置为 1」会让译文多出原文没有的
    阿拉伯数字；真正的改数（5 变 6）和凭空多出的编号仍须拦下。
    """
    assert translation._digits_preserved('A one in any location.', '任意位置为 1。')
    assert translation._digits_preserved('three lanes', '3 条通道')
    assert translation._digits_preserved('two devices', '两个器件')
    assert translation._digits_preserved('Table 2-11 describes', '表 2-11 描述了')
    assert not translation._digits_preserved('Supply 5 V', '电源 6 V')
    assert not translation._digits_preserved('Table 2-11', '表 2-11 和 3-4')
    assert not translation._digits_preserved('Table 2-11', '表 2 11')


@pytest.mark.asyncio
async def test_hyphenated_table_number_survives_translation():
    """连字符编号紧挨着写成两个标记，模型改写其中一个也不能丢弃整段。"""
    plan = {'regions': [{'id': 'p35', 'source':
                         'A one in any location. Table 2-11 describes the register.'}],
            'tables': []}

    async def answer(prompt, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        source = payload['items'][0]['source']
        # 模型把 one 写成 1，并原样保留两个紧挨的标记。
        assert '__KEEP0____KEEP1__' in source
        return json.dumps({'p35': source.replace('one', '1')
                           .replace('A ', '任意位置为 ').replace(' in any location', '。')
                           .replace('Table', '表').replace(' describes the register', ' 描述了该寄存器')}), 'mock'

    targets, warnings = await translation.translate_regions(plan, answer)
    assert not warnings, warnings
    assert '2-11' in targets['p35']
    assert '1' in targets['p35']


def test_tokens_roundtrip():
    source = 'Data output IO1 at -2.5 V and 40 mA, W25Q64BV /CS'
    masked, tokens = translation.protect(source)
    assert translation.restore(masked, tokens) == source
    with pytest.raises(ValueError):
        translation.restore(masked + ' __KEEP0__', tokens)
    masked, tokens = translation.protect('Military/Aerospace Office/Distributors /CS')
    assert masked.startswith('Military/Aerospace Office/Distributors ')
    assert list(tokens.values()) == ['/CS']


@pytest.mark.asyncio
async def test_structured_response_ids_and_retry(source):
    plan = translation.analyze_page(str(source), 1)
    async def answer(prompt, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        return json.dumps({r['id']: '译文 ' + r['source'] for r in payload['items']}), 'mock'
    targets, warnings = await translation.translate_regions(plan, answer)
    assert len(targets) == 3 and not warnings
    bad = AsyncMock(return_value=('{}', 'mock'))
    targets, warnings = await translation.translate_regions(plan, bad)
    assert not targets and len(warnings) == 3
    assert bad.await_count == 2


@pytest.mark.asyncio
async def test_provider_failure_stops_batches_and_exposes_no_raw_credentials():
    plan = {'regions': [{'id': f'p{i}', 'source': 'Description'} for i in range(30)], 'tables': []}
    complete = AsyncMock(side_effect=server.HTTPException(500, 'HTTP 402: Insufficient Balance; secret-key'))
    targets, warnings = await translation.translate_regions(plan, complete)
    assert not targets and len(warnings) == 30 and complete.await_count == 1
    assert all(w['code'] == 'provider_unavailable' for w in warnings)
    assert '余额不足' in warnings[0]['reason']
    assert 'secret-key' not in json.dumps(warnings)


@pytest.mark.asyncio
async def test_invalid_token_retry_receives_feedback():
    plan = {'regions': [{'id': 'p0', 'source': 'Current 20 mA'}], 'tables': []}
    async def answer(prompt, **kwargs):
        item = json.loads(prompt.split('\n', 1)[1])['items'][0]
        if 'validation_feedback' not in item:
            return '{"p0":"电流"}', 'mock'
        assert 'token missing' in item['validation_feedback']
        return '{"p0":"电流 __KEEP0__ mA"}', 'mock'
    targets, warnings = await translation.translate_regions(plan, answer)
    assert targets == {'p0': '电流 20 mA'} and not warnings


def test_retry_keeps_valid_translations_during_provider_outage(source, monkeypatch):
    monkeypatch.setattr(server, 'BOOKS_DIR', str(source.parent.parent))
    initial = AsyncMock(return_value=({'t0r0c0': '编号'}, []))
    monkeypatch.setattr(translation, 'translate_regions', initial)
    with TestClient(server.app) as client:
        original = client.post('/api/pdf-translation/sample', json={'page': 1}).json()
        async def unavailable(plan, complete):
            assert 't0r0c0' not in {r['id'] for r in plan['regions']}
            return {}, [{'id': r['id'], 'code': 'provider_unavailable', 'reason': '服务不可用'}
                        for r in plan['regions']]
        monkeypatch.setattr(translation, 'translate_regions', unavailable)
        report = client.post('/api/pdf-translation/sample', json={'page': 1, 'force': True}).json()
        assert report['translation_count'] == original['translation_count'] == 1
        assert report['placement_count'] == 1 and report['pending_count'] == 2
        assert report['status'] == 'review'
        artifact = client.get(report['pdf_url'])
        with fitz.open(stream=artifact.content, filetype='pdf') as doc:
            assert '编号' in doc[0].get_text().replace(' ', '')


def test_cache_only_never_calls_translation_provider(source, monkeypatch):
    monkeypatch.setattr(server, 'BOOKS_DIR', str(source.parent.parent))
    complete = AsyncMock(return_value=({'t0r0c0': '编号'}, []))
    monkeypatch.setattr(translation, 'translate_regions', complete)
    with TestClient(server.app) as client:
        assert client.post('/api/pdf-translation/sample', json={'page': 1, 'cache_only': True}).status_code == 404
        complete.assert_not_called()
        original = client.post('/api/pdf-translation/sample', json={'page': 1}).json()
        assert complete.await_count == 1
        cached = client.post('/api/pdf-translation/sample', json={'page': 1, 'cache_only': True})
        assert cached.json() == original and complete.await_count == 1
        assert client.post('/api/pdf-translation/sample', json={
            'page': 1, 'force': True, 'cache_only': True}).status_code == 400
        assert client.post('/api/pdf-translation/sample', json={'page': 1, 'cache_only': 'yes'}).status_code == 400


def test_scan_is_explicit_fallback(tmp_path):
    path = tmp_path / 'scan.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert not plan['regions'] and 'OCR' in plan['warnings'][0]['reason']


def test_api_preview_export_cache_and_validation(source, monkeypatch):
    monkeypatch.setattr(server, 'BOOKS_DIR', str(source.parent.parent))
    mock = AsyncMock(return_value=({'t0r0c0': '编号', 't0r0c1': '说明'}, []))
    monkeypatch.setattr(translation, 'translate_regions', mock)
    with TestClient(server.app) as client:
        response = client.post('/api/pdf-translation/sample', json={'page': 1})
        assert response.status_code == 200, response.text
        report = response.json()
        artifact = client.get(report['pdf_url'])
        assert artifact.content.startswith(b'%PDF')
        assert client.post('/api/pdf-translation/sample', json={'page': 1}).json() == report
        assert mock.await_count == 1
        exported = client.get('/api/pdf-translation-download/sample/' + report['version'])
        assert exported.content.startswith(b'%PDF')
        assert client.post('/api/pdf-translation/sample', json={'page': 0}).status_code == 400
        assert client.post('/api/pdf-translation/sample', json={'page': 2}).status_code == 400
        assert client.post('/api/pdf-translation/sample', json={'page': True}).status_code == 400
        assert client.get('/api/pdf-translation-file/sample/bad/1').status_code == 400
    with pytest.raises(server.HTTPException):
        server._structured_pdf_source('..')


def test_local_cli_detection_lists_only_installed():
    """本地 CLI 无需 API Key：只列出本机真正装了的，供用户直接选。"""
    assert server._PROVIDER_DEFS['cli']['format'] == 'cli'
    detected = server._detect_local_clis()
    known_ids = {entry['id'] for entry in server._KNOWN_CLIS}
    # 探测结果必须是已知 CLI 的子集，且每个都带可直接执行的命令模板。
    assert {entry['id'] for entry in detected} <= known_ids
    for entry in detected:
        assert '{prompt}' in entry['command']
        assert shutil.which(entry['id']), entry['id']
    # 每个已知 CLI 都必须交代非交互参数，否则会挂在交互提示上。
    for entry in server._KNOWN_CLIS:
        assert '{prompt}' in entry['command'], entry['id']


def test_cli_provider_needs_no_api_key(monkeypatch):
    """cli 服务商按 enabled 判定"已配置"，不要求 API Key。"""
    monkeypatch.setattr(server, '_ai_config', {
        'providers': {'cli': {'enabled': True, 'api_key': '', 'format': 'cli',
                              'cli_command': 'claude --print "{prompt}"'}},
        'order': ['cli'],
    })
    providers = server._get_enabled_providers()
    assert [p['id'] for p in providers] == ['cli']
    assert providers[0]['cli_command'] == 'claude --print "{prompt}"'


def test_fetch_models_does_not_require_key_for_local_cli():
    """本地 CLI 与 Ollama 不通过 HTTP 暴露模型，不该被要求 API Key。

    此前 fetch-models 对 cli 也走「无 key 即报错」的分支，设置页点「获取模型」
    必然失败（No API key provided）；而 CLI 的模型本就由该命令行工具自行管理。
    """
    with TestClient(server.app) as client:
        cli_result = client.post('/api/ai/fetch-models', json={'id': 'cli'}).json()
        assert 'No API key provided' not in str(cli_result)
        assert '自行管理' in cli_result.get('error', '')
        # Ollama 同样无需 key，应进入网络请求阶段而非被 key 校验拦下。
        ollama_result = client.post('/api/ai/fetch-models', json={'id': 'ollama'}).json()
        assert 'No API key provided' not in str(ollama_result)
        # 真实服务商缺 key 仍须拦下，避免误放宽校验。
        openai_result = client.post('/api/ai/fetch-models', json={'id': 'openai'}).json()
        assert openai_result.get('error') == 'No API key provided'


def test_prefetch_range_control_is_wired():
    """预翻译范围（前后 N 页）必须可选择、可持久化，并在翻页时生效。

    这是纯前端逻辑，用 HTML 源做静态校验，防止下拉被删或接线断开导致设置失效。
    """
    import re
    html_path = Path(__file__).resolve().parents[1] / 'templates' / 'pdf_reader.html'
    html = html_path.read_text(encoding='utf-8')

    match = re.search(r'<select[^>]*id="bilingual-range"[^>]*>(.*?)</select>', html, re.S)
    assert match, '缺少预翻译范围下拉'
    values = re.findall(r'value="(\d+)"', match.group(1))
    assert values and values[0] == '0', f'需要包含「不预取」的 0 选项: {values}'

    for label, pattern in {
        '恢复已保存的范围': r"localStorage\.getItem\('pdf_bilingual_range'\)",
        '修改时持久化': r"localStorage\.setItem\('pdf_bilingual_range'",
        '开启翻译时预取': r'this\._request\(currentPage\); this\._prefetchAround\(currentPage\)',
        '翻页时触发预取': r'window\.Bilingual\?\._onPageChange\(currentPage\)',
        '按范围取前后页': r'Math\.max\(1, page - this\._range\)',
        '不越过末页': r'Math\.min\(pageContainers\.length, page \+ this\._range\)',
    }.items():
        assert re.search(pattern, html), f'预取范围接线缺失: {label}'


def test_selected_model_wins():
    assert server._pick_model({'model': 'chosen', 'default_model': 'default'}) == 'chosen'


def test_vision_request_uses_provider_vision_default():
    """有图片但不能回退到文本模型：DeepSeek 的默认模型不支持图片识别。

    用户在设置里没填「视觉模型」时，旧逻辑会回退到 model（deepseek-flash），
    请求必然拿到「不支持图片识别」。现在改用服务商自带的视觉默认值。
    """
    assert server._PROVIDER_DEFS['deepseek']['vision_model']
    entry = {'model': 'deepseek-flash', 'default_model': 'deepseek-chat',
             'vision_model': '', 'default_vision_model': 'deepseek-v4-flash-vision-exp'}
    assert server._pick_model(entry, images=[b'png']) == 'deepseek-v4-flash-vision-exp'
    # 用户显式配置时以用户为准。
    assert server._pick_model(dict(entry, vision_model='mine'), images=[b'png']) == 'mine'
    # 无图片仍用文本模型，不改变原有行为。
    assert server._pick_model(entry) == 'deepseek-flash'
    # 服务商没有视觉默认值时保持原有回退链。
    plain = {'model': 'text-model', 'default_model': 'fallback'}
    assert server._pick_model(plain, images=[b'png']) == 'text-model'


def test_enabled_providers_expose_vision_default():
    """运行时的 provider 条目要带上服务商视觉默认值，设置页才能提示它。"""
    for entry in server._get_enabled_providers():
        if entry['id'] == 'deepseek':
            assert entry['default_vision_model'] == 'deepseek-v4-flash-vision-exp'
            assert server._pick_model(entry, images=[b'png']) == 'deepseek-v4-flash-vision-exp'
            break


def test_api_stores_final_fit_retry_translations(source, monkeypatch):
    monkeypatch.setattr(server, 'BOOKS_DIR', str(source.parent.parent))
    complete = AsyncMock(side_effect=[({'t0r0c0': '过长译文' * 100}, []), ({'t0r0c0': '编号'}, [])])
    monkeypatch.setattr(translation, 'translate_regions', complete)
    with TestClient(server.app) as client:
        response = client.post('/api/pdf-translation/sample', json={'page': 1})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report['translated'] == 1 and not report['warnings']
        audit = source.parent / '.translated' / report['version'] / 'page-1.audit.json'
        assert json.loads(audit.read_text(encoding='utf-8'))['targets']['t0r0c0'] == '编号'
        assert complete.await_count == 2
        client.post('/api/pdf-translation/sample', json={'page': 1})
        assert complete.await_count == 2


def test_cache_fingerprint_model_change(source):
    assert translation.fingerprint(str(source), 'a') != translation.fingerprint(str(source), 'b')


def test_multiline_paragraph_keeps_original_leading(tmp_path):
    """多行段落必须沿用原文行距，压到 1.05 倍行高会让下行压住上行。

    原文两行行距 14 pt，若按字号 10 pt 的 1.05 倍排版，行距只剩 10.5 pt，
    下行的上伸部会与上行的下伸部重叠。判据直接量输出 PDF 的基线间距。
    """
    path, output = tmp_path / 'leading.pdf', tmp_path / 'leading-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=520, height=300)
        page.insert_text((60, 100), 'The bridge supports pending memory mapped', fontsize=10)
        page.insert_text((60, 114), 'transactions for every configured endpoint.', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    region = plan['regions'][0]
    source_pitch = region['lines'][1]['baseline'] - region['lines'][0]['baseline']
    assert source_pitch > region['font_size'] * 1.2
    report = translation.render_page(str(path), plan, {
        region['id']: '该桥支持每个已配置端点的待处理内存映射事务并逐一完成'}, str(output))
    assert report['placement_count'] == 1 and not report['warnings']
    with fitz.open(output) as doc:
        baselines = [line['spans'][0]['origin'][1]
                     for block in doc[0].get_text('dict')['blocks']
                     for line in block.get('lines', []) if 85 <= line['bbox'][1] <= 150]
    assert len(baselines) == 2, f'译文应折成两行: {baselines}'
    rendered_pitch = baselines[1] - baselines[0]
    # 沿用原文行距（容差 0.5 pt）；旧行为会得到约 10.5 pt。
    assert abs(rendered_pitch - source_pitch) < .5, (
        f'行距未沿用原文: 原文 {source_pitch:.2f} pt，渲染 {rendered_pitch:.2f} pt')


def test_hdl_parameter_names_keep_underscores_and_are_skipped(tmp_path):
    """表格提取会把 HDL 参数名的下划线换成空格，必须按原生字符还原。

    ``C_NO_OF_LANES`` 经 ``extract()`` 变成 ``C NO OF LANES``，模型看到的是
    普通英文词组就会翻译。原生字符里下划线仍在，应以它为准；模型判定无需
    翻译时返回跳过标记，该条目保留原文而不是报成待翻译。
    """
    path, output = tmp_path / 'params.pdf', tmp_path / 'params-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        for y in (60, 90, 120, 150):
            page.draw_line((40, y), (360, y))
        for x in (40, 200, 360):
            page.draw_line((x, 60), (x, 150))
        page.insert_text((50, 80), 'Generic', fontsize=10)
        page.insert_text((210, 80), 'Description', fontsize=10)
        page.insert_text((50, 110), 'C_NO_OF_LANES', fontsize=10)
        page.insert_text((210, 110), 'Number of PCIe lanes', fontsize=10)
        page.insert_text((50, 140), 'C_DEVICE_ID', fontsize=10)
        page.insert_text((210, 140), 'Device identifier', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    sources = {r['id']: r['source'] for r in plan['regions']}
    assert 'C_NO_OF_LANES' in sources.values(), sources
    assert 'C_DEVICE_ID' in sources.values(), sources
    assert not any('C NO OF LANES' in text for text in sources.values())

    parameters = [r['id'] for r in plan['regions'] if '_' in r['source']]

    async def answer(prompt, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        assert translation.SKIP_TOKEN in prompt  # 提示词必须交代跳过约定
        return json.dumps({item['id']: (translation.SKIP_TOKEN if item['id'] in parameters
                                        else '说明') for item in payload['items']}), 'mock'

    targets, warnings = asyncio.run(translation.translate_regions(plan, answer))
    assert not warnings
    assert all(targets[identifier] == sources[identifier] for identifier in parameters)
    report = translation.render_page(str(path), plan, targets, str(output))
    assert report['kept_count'] == len(parameters)
    assert report['pending_count'] == 0
    with fitz.open(output) as doc:
        text = doc[0].get_text()
    for name in ('C_NO_OF_LANES', 'C_DEVICE_ID'):
        assert name in text
    assert '说明' in text.replace(' ', '')


def test_skip_marker_is_not_a_translation():
    """跳过标记本身不能被当作译文写入页面。"""
    assert translation._skip_marker('__SKIP__') is True
    assert translation._skip_marker(' __skip__ ') is True
    assert translation._skip_marker('参数') is False
    assert translation._skip_marker('__KEEP0__') is False
    assert translation._kept('C_NO_OF_LANES', 'C_NO_OF_LANES') is True
    assert translation._kept('C 通道数', 'C NO OF LANES') is False


def test_nested_table_text_is_translated_once(tmp_path):
    """嵌套表格里同一段文字只能生成一个区域，否则译文会重叠渲染。

    外层合并单元格会把内层表的文字再收集一遍。两者各自翻译后渲染到重叠
    坐标，页面上就出现叠字：必须让外层跳过完全落在内层表里的文字。
    """
    path, output = tmp_path / 'nested.pdf', tmp_path / 'nested-zh.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=560, height=400)
        # 外层表：2 行 × 2 列，第 2 行的右侧是一个横跨的合并单元格。
        for y in (60, 100, 260):
            page.draw_line((40, y), (520, y))
        for x in (40, 300, 520):
            page.draw_line((x, 60), (x, 260))
        page.insert_text((50, 85), 'Generic', fontsize=10)
        page.insert_text((310, 85), 'Description', fontsize=10)
        page.insert_text((50, 180), 'G41', fontsize=10)
        # 内层表整块落在该合并单元格内部：2 行 × 2 列。
        for y in (120, 150, 230):
            page.draw_line((310, y), (510, y))
        for x in (310, 410, 510):
            page.draw_line((x, 120), (x, 230))
        page.insert_text((315, 140), 'Parameter Setting', fontsize=9)
        page.insert_text((415, 140), 'Result', fontsize=9)
        page.insert_text((315, 200), 'G1 = Kintex7', fontsize=9)
        page.insert_text((415, 200), 'G41 = 1 or 2', fontsize=9)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['tables']) == 2
    boxes = [(r['id'], fitz.Rect(r['bbox'])) for r in plan['regions']]
    overlaps = [(a, b) for i, (a, box_a) in enumerate(boxes) for b, box_b in boxes[i + 1:]
                if box_a.intersects(box_b) and (box_a & box_b).get_area() > 1]
    assert not overlaps, f'嵌套表格产生了重叠区域: {overlaps}'
    # 内层表的文字归属内层表，外层合并单元格不再重复收集。
    inner = {r['source'] for r in plan['regions'] if r.get('table') == 't1'}
    assert 'Parameter Setting' in inner and 'Result' in inner
    assert not any('Parameter Setting' in r['source'] and r.get('table') == 't0'
                   for r in plan['regions'])
    # 只翻译内层表的文字，成稿里每段文字只出现一次。
    report = translation.render_page(str(path), plan, {
        r['id']: '参数设置' if r['source'] == 'Parameter Setting' else '说明'
        for r in plan['regions'] if r.get('table') == 't1'}, str(output))
    assert not report['warnings']
    with fitz.open(output) as doc:
        text = doc[0].get_text().replace(' ', '')
    assert text.count('参数设置') == 1


def test_page_frame_does_not_swallow_nested_table(tmp_path):
    path = tmp_path / 'framed.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        page.draw_rect(fitz.Rect(20, 20, 380, 580))
        page.insert_text((35, 45), 'Separate heading', fontsize=10)
        for left, right, top in [(20, 380, 250), (90, 310, 70)]:
            for y in (top, top + 30, top + 60):
                page.draw_line((left, y), (right, y))
            for x in (left, (left + right) / 2, right):
                page.draw_line((x, top), (x, top + 60))
            page.insert_text((left + 5, top + 20), 'Parameter', fontsize=10)
            page.insert_text(((left + right) / 2 + 5, top + 20), 'Value', fontsize=10)
            page.insert_text((left + 5, top + 50), 'Voltage', fontsize=10)
            page.insert_text(((left + right) / 2 + 5, top + 50), '10', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['tables']) == 2
    assert all(t['rows'] == 2 for t in plan['tables'])
    assert all(fitz.Rect(r['bbox']).height < 65 for r in plan['regions'])
    assert sum(r['source'] == 'Separate heading' for r in plan['regions']) == 1
    assert sum(r['source'] == 'Parameter' for r in plan['regions']) == 2
    output = tmp_path / 'framed-zh.pdf'
    translation.render_page(str(path), plan, {r['id']: '说明' for r in plan['regions']}, str(output))
    with fitz.open(output) as doc:
        assert doc[0].get_text().count('10') == 2


def test_widely_spaced_footer_keeps_page_number(tmp_path):
    path = tmp_path / 'footer.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((200, 700), '7                                    Revision E ', fontsize=10)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)
    assert len(plan['regions']) == 1
    assert plan['regions'][0]['source'] == 'Revision E'
    output = tmp_path / 'footer-zh.pdf'
    translation.render_page(str(path), plan, {plan['regions'][0]['id']: '修订版 E'}, str(output))
    with fitz.open(output) as doc:
        assert doc[0].search_for('7')[0].x0 == pytest.approx(200)


@pytest.mark.asyncio
async def test_new_digit_beside_chinese_is_rejected():
    plan = {'regions': [{'id': 'p0', 'source': 'Current 20 mA'}], 'tables': []}
    complete = AsyncMock(return_value=('{"p0":"电流__KEEP0__ mA，另有7"}', 'mock'))
    targets, warnings = await translation.translate_regions(plan, complete)
    assert not targets and warnings


def test_model_identifier_is_not_prose():
    assert not translation.needs_translation('W25Q64BV')
    assert translation.needs_translation('PIN NAME')


def test_reference_only_labels_never_enter_the_translation_queue():
    """编号标签和纯型号/数值无法中文化，留作待翻译只会变成永不消失的噪声。"""
    assert translation._verbatim('Verilog', 'Verilog') is True
    assert translation._verbatim('XDC', 'XDC') is True
    assert translation._verbatim('(1)', '(1)') is True
    assert translation._verbatim('25 MHz', '25 MHz') is True
    assert translation._verbatim('Verilog', 'VHDL and Verilog') is False
    assert translation._verbatim('Device Family', 'Device Family') is False
    assert translation._verbatim('a longer untranslated sentence that was echoed back',
                                'a longer untranslated sentence that was echoed back') is False


def test_echoed_short_identifier_is_kept_not_pending(source, tmp_path):
    """模型原样返回短标识符时应判为「无需翻译」，页面不该永远显示待翻译。"""
    plan = translation.analyze_page(str(source), 1)
    targets = {'t0r0c0': 'Code', 't0r0c1': '说明'}
    report = translation.render_page(str(source), plan, targets, str(tmp_path / 'kept.pdf'))
    details = {d['id']: d for d in report['details']}
    assert details['t0r0c0']['status'] == 'kept' and report['kept_count'] == 1
    assert report['pending_count'] == 1 and report['unplaced_count'] == 0
    assert details['t0r1c1']['status'] == 'pending'
    assert report['translation_count'] == 1 and report['placement_count'] == 1
    with fitz.open(tmp_path / 'kept.pdf') as doc:
        text = doc[0].get_text()
        assert 'Code' in text and '说明' in text.replace(' ', '')


def test_note_label_period_survives_a_chinese_rewrite():
    """模型常把标签句点写成中文句号，编号必须按原文还原。"""
    masked, tokens = translation.protect('1. For the supported tools')
    assert list(tokens.values()) == ['1.'] and '__KEEP0__' in masked
    assert translation.restore('1。欲了解受支持的工具', tokens) == '1. 欲了解受支持的工具'
    assert translation.restore('1．欲了解受支持的工具', tokens) == '1. 欲了解受支持的工具'
    assert translation.restore('1. 欲了解受支持的工具', tokens) == '1. 欲了解受支持的工具'
    with pytest.raises(ValueError):
        translation.restore('完全没有编号的译文', tokens)


def test_numbered_note_keeps_ascii_period_end_to_end(tmp_path):
    """端到端：模型把标签写成全角句号时，成稿仍写出原编号。"""
    path = tmp_path / 'note.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=200)
        page.insert_text((40, 80), '1.  For the supported versions of tools', fontsize=8)
        doc.save(path)
    plan = translation.analyze_page(str(path), 1)

    async def answer(prompt, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        return json.dumps({r['id']: '1。有关受支持的工具版本' for r in payload['items']}), 'mock'

    targets, warnings = asyncio.run(translation.translate_regions(plan, answer))
    assert not warnings
    assert list(targets.values()) == ['1. 有关受支持的工具版本']


def test_same_style_words_merge_but_subscripts_do_not():
    def span(text, x, size=10, baseline=20):
        return {'text': text, 'font': 'Helvetica', 'size': size, 'origin': (x, baseline),
                'bbox': (x, baseline - size, x + len(text) * 5, baseline),
                'chars': [{'c': char, 'origin': (x + i * 5, baseline),
                           'bbox': (x + i * 5, baseline - size, x + (i + 1) * 5, baseline)}
                          for i, char in enumerate(text)]}
    words = translation._coalesce_spans([span('Limits', 10), span('are', 43),
                                        span('currently', 61), span('tested', 109)])
    assert len(words) == 1 and words[0]['text'] == 'Limits are currently tested'
    formula = translation._coalesce_spans([span('V', 10), span('CC', 15, size=7, baseline=22)])
    assert len(formula) == 2


@pytest.mark.asyncio
async def test_fenced_json_response_is_accepted():
    plan = {'regions': [{'id': 'p0', 'source': 'Description'}], 'tables': []}
    complete = AsyncMock(return_value=('```json\n{"p0":"说明"}\n```', 'mock'))
    targets, warnings = await translation.translate_regions(plan, complete)
    assert targets == {'p0': '说明'} and not warnings


def test_rotation_and_detection_failure_keep_page(source, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('failed detection')
    monkeypatch.setattr(fitz.Page, 'find_tables', fail)
    plan = translation.analyze_page(str(source), 1)
    assert not plan['regions'] and plan['warnings']
    with fitz.open(source) as doc:
        doc[0].set_rotation(90)
        doc.saveIncr()
    plan = translation.analyze_page(str(source), 1)
    assert not plan['regions'] and plan['warnings']


@pytest.mark.asyncio
async def test_translation_never_uses_reasoning_as_final(monkeypatch):
    response = SimpleNamespace(status_code=200, json=lambda: {
        'choices': [{'message': {'content': '', 'reasoning_content': 'not a translation'}}]})
    monkeypatch.setattr(server, '_ai_client', SimpleNamespace(post=AsyncMock(return_value=response)))
    with pytest.raises(ValueError, match='最终译文'):
        await server._call_openai_compat('https://example.test', 'test', 'm', 'p', .1, 100, final_only=True)


@pytest.mark.asyncio
async def test_deepseek_translation_disables_thinking_only_for_translation(monkeypatch):
    monkeypatch.setattr(server, '_get_enabled_providers', lambda: [{
        'id': 'deepseek', 'name': 'DeepSeek', 'format': 'openai', 'model': 'selected',
        'base_url': 'https://example.test', 'api_key': 'test'}])
    call = AsyncMock(return_value='{}')
    monkeypatch.setattr(server, '_call_openai_compat', call)
    await server._ai_complete('translate', task='translate')
    assert call.call_args.kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert call.call_args.kwargs['final_only'] is True
    await server._ai_complete('chat')
    assert call.call_args.kwargs['extra_body'] is None
    assert call.call_args.kwargs['final_only'] is False
