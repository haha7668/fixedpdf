import os
import pickle
import runpy
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pytest
from bs4 import BeautifulSoup

from reader3 import (
    Book,
    BookMetadata,
    ChapterContent,
    Link,
    Section,
    TOCEntry,
    _ManifestItem,
    clean_html_content,
    extract_metadata_robust,
    extract_plain_text,
    get_fallback_toc,
    parse_toc_recursive,
    process_epub,
    save_to_pickle,
)

# --- Helper fixtures ---


@pytest.fixture
def sample_html():
    return """
    <html>
    <head><title>Test</title></head>
    <body>
        <h1>Hello World</h1>
        <p>This is a <b>test</b> paragraph.</p>
        <script>alert('xss')</script>
        <style>.hidden{display:none}</style>
        <nav>Navigation</nav>
        <iframe src="evil.com"></iframe>
        <!-- comment -->
        <input type="hidden" value="secret">
        <img src="images/test.jpg" alt="test">
        <img src="../images/cover.png" alt="cover">
    </body>
    </html>
    """


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


# --- 标准库实现的 EPUB 生成器（替代 EbookLib） ---

def _write_epub(path, *, title="Test Book", author="Author", language="en",
                chapters=(), images=(), nav=None, ncx=None, cover_meta_id=None):
    """用 zipfile + 手写 XML 生成一个最小可解析的 EPUB。

    chapters: [(href, html_bytes_or_str), ...]
    images:   [(href, content_bytes, media_type), ...]
    nav:      nav.xhtml 内容（EPUB3 TOC）
    ncx:      toc.ncx 内容（EPUB2 TOC）
    cover_meta_id: OPF <meta name="cover" content="..."> 指向的 manifest id
    """
    entries = {}

    entries['META-INF/container.xml'] = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        b'<rootfiles><rootfile full-path="OEBPS/content.opf" '
        b'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )

    manifest_items = []

    def add_item(item_id, href, media_type, properties=''):
        manifest_items.append((item_id, href, media_type, properties))

    for i, (href, content) in enumerate(chapters):
        add_item(f'ch{i}', href, 'application/xhtml+xml')
        entries['OEBPS/' + href] = content if isinstance(content, bytes) else content.encode('utf-8')

    for i, (href, content, media_type) in enumerate(images):
        add_item(f'img{i}', href, media_type)
        entries['OEBPS/' + href] = content

    if nav is not None:
        add_item('nav', 'nav.xhtml', 'application/xhtml+xml', properties='nav')
        entries['OEBPS/nav.xhtml'] = nav if isinstance(nav, bytes) else nav.encode('utf-8')

    if ncx is not None:
        add_item('ncx', 'toc.ncx', 'application/x-dtbncx+xml')
        entries['OEBPS/toc.ncx'] = ncx if isinstance(ncx, bytes) else ncx.encode('utf-8')

    spine_ids = [mid for mid, _, _, _ in manifest_items if mid.startswith('ch')]
    spine_xml = ''.join(f'<itemref idref="{mid}"/>' for mid in spine_ids)

    manifest_xml = ''.join(
        f'<item id="{mid}" href="{href}" media-type="{mt}"'
        + (f' properties="{p}"' if p else '') + '/>'
        for mid, href, mt, p in manifest_items
    )

    meta_cover = f'<meta name="cover" content="{cover_meta_id}"/>' if cover_meta_id else ''

    spine_attrs = ' toc="ncx"' if ncx is not None else ''
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="id">test-id</dc:identifier>'
        f'<dc:title>{title}</dc:title>'
        f'<dc:language>{language}</dc:language>'
        f'<dc:creator>{author}</dc:creator>'
        f'{meta_cover}'
        '</metadata>'
        f'<manifest>{manifest_xml}</manifest>'
        f'<spine{spine_attrs}>{spine_xml}</spine>'
        '</package>'
    ).encode()
    entries['OEBPS/content.opf'] = opf

    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _create_minimal_epub(path, title="Test Book", author="Author", chapters=None):
    if chapters is None:
        chapters = [
            ("Chapter 1", "<h1>Chapter 1</h1><p>Content of chapter 1. " + "word " * 20 + "</p>"),
            ("Chapter 2", "<h1>Chapter 2</h1><p>Content of chapter 2. " + "word " * 20 + "</p>"),
        ]
    _write_epub(
        path, title=title, author=author,
        chapters=[(f'chap_{i:02d}.xhtml', html) for i, (_, html) in enumerate(chapters)],
    )
    return path


def _create_epub_with_images(path):
    _write_epub(
        path,
        title='Book With Images', author='Img Author',
        chapters=[('intro.xhtml', '<html><body><h1>Intro</h1><p>Content.</p></body></html>')],
        images=[('images/cover.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'image/jpeg')],
    )
    return path


def _create_epub_with_short_chapters(path):
    _write_epub(
        path,
        title='Short Chapter Book', author='Author',
        chapters=[
            ('long.xhtml', '<html><body><h1>Chapter</h1><p>' + 'word ' * 20 + '</p></body></html>'),
            ('short.xhtml', '<p>X</p>'),
        ],
    )
    return path


_NAV_NESTED = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Nav</title></head><body>'
    '<nav epub:type="toc"><h1>Contents</h1><ol>'
    '<li><span>Part I</span><ol>'
    '<li><a href="p1.xhtml">Chapter 1</a></li>'
    '<li><a href="p2.xhtml">Chapter 2</a></li>'
    '</ol></li>'
    '</ol></nav></body></html>'
)


def _create_epub_with_toc_sections(path):
    _write_epub(
        path,
        title='Nested TOC Book', author='Author',
        chapters=[
            ('p1.xhtml', '<html><body><h1>Part 1</h1><p>Content one.</p></body></html>'),
            ('p2.xhtml', '<html><body><h1>Part 2</h1><p>Content two.</p></body></html>'),
        ],
        nav=_NAV_NESTED,
    )
    return path


# --- clean_html_content tests ---

class TestCleanHtmlContent:
    def test_removes_script(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('script') is None

    def test_removes_style(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('style') is None

    def test_removes_nav(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('nav') is None

    def test_removes_iframe(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('iframe') is None

    def test_removes_comments(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        from bs4 import Comment
        comments = result.find_all(string=lambda text: isinstance(text, Comment))
        assert len(comments) == 0

    def test_removes_input(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('input') is None

    def test_preserves_paragraphs(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        assert result.find('p') is not None

    def test_preserves_images(self, sample_html):
        soup = BeautifulSoup(sample_html, 'html.parser')
        result = clean_html_content(soup)
        imgs = result.find_all('img')
        assert len(imgs) == 2


# --- extract_plain_text tests ---

class TestExtractPlainText:
    def test_basic_extraction(self):
        html = '<html><body><h1>Title</h1><p>Hello world.</p></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        text = extract_plain_text(soup)
        assert 'Title' in text
        assert 'Hello world.' in text

    def test_collapses_whitespace(self):
        html = '<p>  lots   of    spaces  </p>'
        soup = BeautifulSoup(html, 'html.parser')
        text = extract_plain_text(soup)
        assert '  ' not in text

    def test_empty_content(self):
        soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
        text = extract_plain_text(soup)
        assert text == ''


# --- parse_toc_recursive tests ---

class TestParseTocRecursive:
    def test_simple_links(self):
        links = [
            Link('ch1.xhtml', 'Chapter 1', 'ch1'),
            Link('ch2.xhtml', 'Chapter 2', 'ch2'),
        ]
        result = parse_toc_recursive(links)
        assert len(result) == 2
        assert result[0].title == 'Chapter 1'
        assert result[0].file_href == 'ch1.xhtml'
        assert result[0].anchor == ''
        assert result[1].title == 'Chapter 2'

    def test_link_with_anchor(self):
        links = [Link('ch1.xhtml#sec1', 'Section 1', 's1')]
        result = parse_toc_recursive(links)
        assert len(result) == 1
        assert result[0].file_href == 'ch1.xhtml'
        assert result[0].anchor == 'sec1'

    def test_nested_section(self):
        child_link = Link('ch1.xhtml', 'Child', 'c1')
        section = Section('Part I')
        result = parse_toc_recursive([(section, [child_link])])
        assert len(result) == 1
        assert result[0].title == 'Part I'
        assert len(result[0].children) == 1
        assert result[0].children[0].title == 'Child'
        assert result[0].children[0].file_href == 'ch1.xhtml'

    def test_empty_toc(self):
        result = parse_toc_recursive([])
        assert result == []

    def test_section_item(self):
        sec = Section('Section A')
        sec.href = 'sec_a.xhtml'
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].title == 'Section A'
        assert result[0].file_href == 'sec_a.xhtml'

    def test_bad_toc_item_skipped(self):
        class BadItem:
            pass
        good = Link('ch1.xhtml', 'Good', 'ch1')
        result = parse_toc_recursive([good, BadItem(), Link('ch2.xhtml', 'Good2', 'ch2')])
        assert len(result) == 2

    def test_tuple_with_bad_section(self):
        Link('ch1.xhtml', 'Ch1', 'ch1')
        result = parse_toc_recursive([(42,)])
        assert result == []

    def test_parse_toc_bad_items(self):
        result = parse_toc_recursive([123, None, "bad"])
        assert result == []

    def test_parse_toc_mixed(self):
        items = [Link('ch1.xhtml', 'Ch1', 'ch1'), 123, Link('ch2.xhtml', 'Ch2', 'ch2')]
        result = parse_toc_recursive(items)
        assert len(result) == 2

    def test_section_with_link_items(self):
        link = Link('ch1.xhtml', 'Ch1', 'ch1')
        sec = Section('Part')
        sec.href = [link]
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].href == 'ch1.xhtml'

    def test_section_with_str_items(self):
        sec = Section('Part')
        sec.href = ["section.html"]
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].href == 'section.html'

    def test_toc_section_with_anchor(self):
        sec = Section('Part')
        sec.href = "section.html#anchor1"
        result = parse_toc_recursive([sec])
        assert result[0].anchor == 'anchor1'
        assert result[0].file_href == 'section.html'

    def test_section_with_empty_list(self):
        sec = Section('Part')
        sec.href = []
        result = parse_toc_recursive([sec])
        assert len(result) == 1


# --- get_fallback_toc tests ---

class TestGetFallbackToc:
    def test_builds_from_documents(self):
        items = [
            _ManifestItem(id='1', href='chapter1.html', media_type='application/xhtml+xml'),
            _ManifestItem(id='2', href='introduction.xhtml', media_type='application/xhtml+xml'),
            _ManifestItem(id='3', href='cover.jpg', media_type='image/jpeg'),
        ]
        toc = get_fallback_toc(items)
        assert len(toc) == 2
        assert toc[0].file_href == 'chapter1.html'
        assert toc[1].file_href == 'introduction.xhtml'


# --- extract_metadata_robust tests ---

class TestExtractMetadataRobust:
    def test_extracts_basic_metadata(self):
        metadata = {
            'title': ['My Book'],
            'language': ['en'],
            'creator': ['Author One', 'Author Two'],
            'description': ['A great book.'],
            'publisher': ['Pub Co'],
            'date': ['2024-01-01'],
            'identifier': ['isbn-123'],
            'subject': ['fiction', 'adventure'],
        }
        meta = extract_metadata_robust(metadata)
        assert meta.title == 'My Book'
        assert meta.language == 'en'
        assert meta.authors == ['Author One', 'Author Two']
        assert meta.description == 'A great book.'
        assert meta.publisher == 'Pub Co'
        assert meta.date == '2024-01-01'
        assert meta.identifiers == ['isbn-123']
        assert meta.subjects == ['fiction', 'adventure']

    def test_defaults_when_empty(self):
        meta = extract_metadata_robust({})
        assert meta.title == 'Untitled'
        assert meta.language == 'en'
        assert meta.authors == []


# --- process_epub tests ---

class TestProcessEpub:
    def test_basic_processing(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'test.epub')
        _create_minimal_epub(epub_path)
        out_dir = os.path.join(tmp_dir, 'output')
        book = process_epub(epub_path, out_dir)
        assert isinstance(book, Book)
        assert book.metadata.title == 'Test Book'
        assert book.metadata.authors == ['Author']
        assert len(book.spine) == 2
        assert book.source_file == 'test.epub'
        assert book.version == '3.0'

    def test_images_extraction(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_test.epub')
        _create_epub_with_images(epub_path)
        out_dir = os.path.join(tmp_dir, 'img_output')
        book = process_epub(epub_path, out_dir)
        assert len(book.images) > 0

    def test_short_chapters_skipped(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'short.epub')
        _create_epub_with_short_chapters(epub_path)
        out_dir = os.path.join(tmp_dir, 'short_output')
        book = process_epub(epub_path, out_dir)
        assert len(book.spine) >= 1
        assert book.spine[0].text != ''
        assert book.spine[0].title == 'Section 1'

    def test_nested_toc(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'toc_test.epub')
        _create_epub_with_toc_sections(epub_path)
        out_dir = os.path.join(tmp_dir, 'toc_output')
        book = process_epub(epub_path, out_dir)
        assert len(book.toc) == 1
        assert len(book.toc[0].children) == 2

    def test_overwrite_existing(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'overwrite.epub')
        _create_minimal_epub(epub_path)
        out_dir = os.path.join(tmp_dir, 'overwrite_output')

        book1 = process_epub(epub_path, out_dir)
        save_to_pickle(book1, out_dir)
        assert os.path.exists(os.path.join(out_dir, 'book.pkl'))

        book2 = process_epub(epub_path, out_dir)
        assert book2.metadata.title == book1.metadata.title

    def test_chapter_content_is_html(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'html_test.epub')
        _create_minimal_epub(epub_path, chapters=[
            ("Ch1", "<html><body><h1>Ch1</h1><p>Hello <b>bold</b> world</p></body></html>")
        ])
        out_dir = os.path.join(tmp_dir, 'html_output')
        book = process_epub(epub_path, out_dir)
        assert '<b>bold</b>' in book.spine[0].content

    def test_chapter_text_plain(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'text_test.epub')
        _create_minimal_epub(epub_path, chapters=[
            ("Ch1", "<html><body><p>Plain text content here.</p></body></html>")
        ])
        out_dir = os.path.join(tmp_dir, 'text_output')
        book = process_epub(epub_path, out_dir)
        assert 'Plain text content here.' in book.spine[0].text

    def test_cover_from_opf_meta(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'cover_opf.epub')
        _write_epub(
            epub_path,
            title='Cover OPF', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text to pass checks.</p></body></html>')],
            images=[('images/cover.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'opf_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_epub3_item_cover(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'epub3_cover.epub')
        _write_epub(
            epub_path,
            title='EPUB3 Cover', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text.</p></body></html>')],
            images=[('images/cover.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'epub3_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_opf_bad_item_id(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'bad_cover_id.epub')
        _write_epub(
            epub_path,
            title='Bad Cover ID', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text.</p></body></html>')],
            cover_meta_id='nonexistent-id',
        )
        out_dir = os.path.join(tmp_dir, 'bad_id_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_from_opf_meta_content(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'opf_cover.epub')
        _write_epub(
            epub_path,
            title='OPF Cover', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text to pass.</p></body></html>')],
            images=[('images/cover.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'image/jpeg')],
            cover_meta_id='img0',
        )
        out_dir = os.path.join(tmp_dir, 'opf_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_image_error_handling(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'cover_err.epub')
        _write_epub(
            epub_path,
            title='Cover Err Book', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text to pass the minimum length check for chapters.</p></body></html>')],
            images=[('images/bad_cover.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 50, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'cover_err_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_nav_skipped_in_nonspine(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'nav_skip.epub')
        _write_epub(
            epub_path,
            title='Nav Skip', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text to pass.</p></body></html>')],
            nav='<html><body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">Ch1</a></li></ol></nav></body></html>',
        )
        out_dir = os.path.join(tmp_dir, 'nav_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_short_doc_after_first(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'short_doc.epub')
        _write_epub(
            epub_path,
            title='Short Doc', author='Author',
            chapters=[
                ('long.xhtml', '<html><body><p>' + 'word ' * 30 + '</p></body></html>'),
                ('short.xhtml', '<p>X</p>'),
            ],
        )
        out_dir = os.path.join(tmp_dir, 'short_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_image_src_full_path(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_remap.epub')
        _write_epub(
            epub_path,
            title='Img Remap', author='Author',
            chapters=[('ch1.xhtml', '<html><body><img src="../images/photo.jpg"/><p>Content with enough text.</p></body></html>')],
            images=[('images/photo.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 50, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'remap_out')
        result = process_epub(epub_path, out_dir)
        assert 'images/photo.jpg' in result.spine[0].content

    def test_no_body_uses_soup(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'nobody.epub')
        _write_epub(
            epub_path,
            title='NoBody', author='Author',
            chapters=[('ch1.xhtml', '<div><p>No body tag but enough content to pass.</p></div>')],
        )
        out_dir = os.path.join(tmp_dir, 'nobody_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_image_path_normalization(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_test.epub')
        _write_epub(
            epub_path,
            title='Image Test', author='Author',
            chapters=[('ch1.xhtml', '<html><body><img src="../images/test.jpg"/><p>Content here.</p></body></html>')],
            images=[('images/test.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 50, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'img_output')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) == 1
        assert 'images/test.jpg' in result.spine[0].content

    def test_image_write_error(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_err.epub')
        _write_epub(
            epub_path,
            title='Image Error', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>Content with enough text.</p></body></html>')],
            images=[('images/test.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'image/jpeg')],
        )
        out_dir = os.path.join(tmp_dir, 'img_err_out')
        os.makedirs(out_dir, exist_ok=True)
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_chapter_error_continues(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'ch_err.epub')
        _write_epub(
            epub_path,
            title='Chapter Error', author='Author',
            chapters=[
                ('good.xhtml', '<html><body><p>Good chapter with enough text.</p></body></html>'),
                ('bad.xhtml', '<html><body><p>Bad chapter.</p></body></html>'),
            ],
        )
        out_dir = os.path.join(tmp_dir, 'ch_err_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1


# --- save_to_pickle tests ---

class TestSaveToPickle:
    def test_save_and_load(self, tmp_dir):
        metadata = BookMetadata(title='Pickle Test', language='en', authors=['Tester'])
        chapter = ChapterContent(id='c1', href='c1.xhtml', title='Ch1',
                                 content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=metadata, spine=[chapter], toc=[], images={},
                    source_file='test.epub', processed_at='2024-01-01T00:00:00')

        save_to_pickle(book, tmp_dir)
        pkl_path = os.path.join(tmp_dir, 'book.pkl')
        assert os.path.exists(pkl_path)

        with open(pkl_path, 'rb') as f:
            loaded = pickle.load(f)
        assert loaded.metadata.title == 'Pickle Test'
        assert len(loaded.spine) == 1


# --- Data class tests ---

class TestDataClasses:
    def test_chapter_content_defaults(self):
        ch = ChapterContent(id='1', href='f.html', title='T', content='c', text='t', order=0)
        assert ch.id == '1'

    def test_toc_entry_children_default(self):
        entry = TOCEntry(title='T', href='h', file_href='f', anchor='a')
        assert entry.children == []

    def test_book_metadata_defaults(self):
        meta = BookMetadata(title='T', language='en')
        assert meta.authors == []
        assert meta.description is None
        assert meta.publisher is None
        assert meta.date is None
        assert meta.identifiers == []
        assert meta.subjects == []

    def test_book_defaults(self):
        meta = BookMetadata(title='T', language='en')
        book = Book(metadata=meta, spine=[], toc=[], images={},
                    source_file='test.epub', processed_at='2024-01-01')
        assert book.version == '3.0'


# --- CLI tests ---

class TestCLI:
    def test_cli_no_args(self):
        result = subprocess.run(
            [sys.executable, 'reader3.py'],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )
        assert result.returncode == 1
        assert 'Usage' in result.stdout

    def test_cli_nonexistent_file(self):
        result = subprocess.run(
            [sys.executable, 'reader3.py', '/nonexistent/file.epub'],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )
        assert result.returncode != 0

    def test_cli_no_args_runpy(self):
        old_argv = sys.argv[:]
        sys.argv = ['reader3.py']
        try:
            with pytest.raises(SystemExit):
                runpy.run_path('reader3.py', run_name='__main__')
        finally:
            sys.argv = old_argv

    def test_cli_with_epub(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'cli_test.epub')
        _write_epub(
            epub_path,
            title='CLI Test', author='Author',
            chapters=[('ch1.xhtml', '<html><body><p>CLI test content.</p></body></html>')],
        )

        old_argv = sys.argv[:]
        sys.argv = ['reader3.py', epub_path]
        try:
            runpy.run_path('reader3.py', run_name='__main__')
        finally:
            sys.argv = old_argv
        out_dir = os.path.splitext(epub_path)[0] + '_data'
        assert os.path.exists(os.path.join(out_dir, 'book.pkl'))

    def test_cli_nonexistent_file_runpy(self):
        old_argv = sys.argv[:]
        sys.argv = ['reader3.py', '/nonexistent/file.epub']
        try:
            with pytest.raises(AssertionError):
                runpy.run_path('reader3.py', run_name='__main__')
        finally:
            sys.argv = old_argv
