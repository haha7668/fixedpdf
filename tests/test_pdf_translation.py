import json
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


def test_selected_model_wins():
    assert server._pick_model({'model': 'chosen', 'default_model': 'default'}) == 'chosen'


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
