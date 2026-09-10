import os
import pickle
import runpy
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from reader3 import (
    Book,
    BookMetadata,
    ChapterContent,
    TOCEntry,
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


def _create_minimal_epub(path, title="Test Book", author="Author", chapters=None):
    book = epub.EpubBook()
    book.set_identifier('test-id-123')
    book.set_title(title)
    book.set_language('en')
    book.add_author(author)

    if chapters is None:
        chapters = [("Chapter 1", "<h1>Chapter 1</h1><p>Content of chapter 1.</p>"),
                     ("Chapter 2", "<h1>Chapter 2</h1><p>Content of chapter 2.</p>")]

    spine_items = []
    for i, (ch_title, ch_html) in enumerate(chapters):
        c = epub.EpubHtml(title=ch_title, file_name=f'chap_{i:02d}.xhtml', lang='en')
        c.content = ch_html.encode('utf-8')
        book.add_item(c)
        spine_items.append(c)

    book.toc = [epub.Link(f'chap_{i:02d}.xhtml', t, f'chap_{i:02d}') for i, (t, _) in enumerate(chapters)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    epub.write_epub(path, book, {})
    return path


def _create_epub_with_images(path):
    book = epub.EpubBook()
    book.set_identifier('img-test-id')
    book.set_title('Book With Images')
    book.set_language('en')
    book.add_author('Img Author')

    c = epub.EpubHtml(title='Intro', file_name='intro.xhtml', lang='en')
    c.content = b'<html><body><h1>Intro</h1><p>Content.</p></body></html>'
    book.add_item(c)

    img = epub.EpubImage()
    img.file_name = 'images/cover.jpg'
    img.media_type = 'image/jpeg'
    img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
    book.add_item(img)

    book.toc = [epub.Link('intro.xhtml', 'Intro', 'intro')]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c]
    epub.write_epub(path, book, {})
    return path


def _create_epub_with_short_chapters(path):
    book = epub.EpubBook()
    book.set_identifier('short-test-id')
    book.set_title('Short Chapter Book')
    book.set_language('en')

    long = epub.EpubHtml(title='Long Chapter', file_name='long.xhtml', lang='en')
    long.content = b'<html><body><h1>Chapter</h1><p>' + b'word ' * 20 + b'</p></body></html>'
    book.add_item(long)

    short = epub.EpubHtml(title='Short', file_name='short.xhtml', lang='en')
    short.content = b'<p>X</p>'
    book.add_item(short)

    book.toc = [epub.Link('long.xhtml', 'Long', 'long'),
                epub.Link('short.xhtml', 'Short', 'short')]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [long, short]
    epub.write_epub(path, book, {})
    return path


def _create_epub_with_toc_sections(path):
    book = epub.EpubBook()
    book.set_identifier('toc-test-id')
    book.set_title('Nested TOC Book')
    book.set_language('en')

    c1 = epub.EpubHtml(title='Part 1', file_name='p1.xhtml', lang='en')
    c1.content = b'<html><body><h1>Part 1</h1><p>Content one.</p></body></html>'
    book.add_item(c1)

    c2 = epub.EpubHtml(title='Part 2', file_name='p2.xhtml', lang='en')
    c2.content = b'<html><body><h1>Part 2</h1><p>Content two.</p></body></html>'
    book.add_item(c2)

    link1 = epub.Link('p1.xhtml', 'Chapter 1', 'ch1')
    link2 = epub.Link('p2.xhtml', 'Chapter 2', 'ch2')
    section = epub.Section('Part I')
    book.toc = [(section, [link1, link2])]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c1, c2]
    epub.write_epub(path, book, {})
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
            epub.Link('ch1.xhtml', 'Chapter 1', 'ch1'),
            epub.Link('ch2.xhtml', 'Chapter 2', 'ch2'),
        ]
        result = parse_toc_recursive(links)
        assert len(result) == 2
        assert result[0].title == 'Chapter 1'
        assert result[0].file_href == 'ch1.xhtml'
        assert result[0].anchor == ''
        assert result[1].title == 'Chapter 2'

    def test_link_with_anchor(self):
        links = [epub.Link('ch1.xhtml#sec1', 'Section 1', 's1')]
        result = parse_toc_recursive(links)
        assert len(result) == 1
        assert result[0].file_href == 'ch1.xhtml'
        assert result[0].anchor == 'sec1'

    def test_nested_section(self):
        child_link = epub.Link('ch1.xhtml', 'Child', 'c1')
        section = epub.Section('Part I')
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
        sec = epub.Section('Section A')
        sec.href = 'sec_a.xhtml'
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].title == 'Section A'
        assert result[0].file_href == 'sec_a.xhtml'

    def test_bad_toc_item_skipped(self):
        class BadItem:
            pass
        good = epub.Link('ch1.xhtml', 'Good', 'ch1')
        result = parse_toc_recursive([good, BadItem(), epub.Link('ch2.xhtml', 'Good2', 'ch2')])
        assert len(result) == 2

    def test_tuple_with_bad_section(self):
        epub.Link('ch1.xhtml', 'Ch1', 'ch1')
        result = parse_toc_recursive([(42,)])
        assert result == []

    def test_parse_toc_bad_items(self):
        result = parse_toc_recursive([123, None, "bad"])
        assert result == []

    def test_parse_toc_mixed(self):
        items = [epub.Link('ch1.xhtml', 'Ch1', 'ch1'), 123, epub.Link('ch2.xhtml', 'Ch2', 'ch2')]
        result = parse_toc_recursive(items)
        assert len(result) == 2

    def test_section_with_link_items(self):
        link = epub.Link('ch1.xhtml', 'Ch1', 'ch1')
        sec = epub.Section('Part')
        sec.href = [link]
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].href == 'ch1.xhtml'

    def test_section_with_str_items(self):
        sec = epub.Section('Part')
        sec.href = ["section.html"]
        result = parse_toc_recursive([sec])
        assert len(result) == 1
        assert result[0].href == 'section.html'

    def test_toc_section_with_anchor(self):
        sec = epub.Section('Part')
        sec.href = "section.html#anchor1"
        result = parse_toc_recursive([sec])
        assert result[0].anchor == 'anchor1'
        assert result[0].file_href == 'section.html'

    def test_section_with_empty_list(self):
        sec = epub.Section('Part')
        sec.href = []
        result = parse_toc_recursive([sec])
        assert len(result) == 1


# --- get_fallback_toc tests ---

class TestGetFallbackToc:
    def test_builds_from_documents(self):
        import ebooklib
        mock_book = MagicMock()
        item1 = MagicMock()
        item1.get_type.return_value = ebooklib.ITEM_DOCUMENT
        item1.get_name.return_value = 'chapter1.html'

        item2 = MagicMock()
        item2.get_type.return_value = ebooklib.ITEM_DOCUMENT
        item2.get_name.return_value = 'introduction.xhtml'

        item3 = MagicMock()
        item3.get_type.return_value = ebooklib.ITEM_IMAGE
        item3.get_name.return_value = 'cover.jpg'

        mock_book.get_items.return_value = [item1, item2, item3]
        toc = get_fallback_toc(mock_book)
        assert len(toc) == 2
        assert toc[0].file_href == 'chapter1.html'
        assert toc[1].file_href == 'introduction.xhtml'


# --- extract_metadata_robust tests ---

class TestExtractMetadataRobust:
    def test_extracts_basic_metadata(self):
        mock_book = MagicMock()
        mock_book.get_metadata.side_effect = lambda ns, key: {
            ('DC', 'title'): [('My Book',)],
            ('DC', 'language'): [('en',)],
            ('DC', 'creator'): [('Author One',), ('Author Two',)],
            ('DC', 'description'): [('A great book.',)],
            ('DC', 'publisher'): [('Pub Co',)],
            ('DC', 'date'): [('2024-01-01',)],
            ('DC', 'identifier'): [('isbn-123',)],
            ('DC', 'subject'): [('fiction',), ('adventure',)],
        }.get((ns, key), [])

        meta = extract_metadata_robust(mock_book)
        assert meta.title == 'My Book'
        assert meta.language == 'en'
        assert meta.authors == ['Author One', 'Author Two']
        assert meta.description == 'A great book.'
        assert meta.publisher == 'Pub Co'
        assert meta.date == '2024-01-01'
        assert meta.identifiers == ['isbn-123']
        assert meta.subjects == ['fiction', 'adventure']

    def test_defaults_when_empty(self):
        mock_book = MagicMock()
        mock_book.get_metadata.return_value = []
        meta = extract_metadata_robust(mock_book)
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
        book = epub.EpubBook()
        book.set_identifier('cover-opf-id')
        book.set_title('Cover OPF')
        book.set_language('en')

        img = epub.EpubImage()
        img.file_name = 'images/cover.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        book.add_item(img)

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text to pass checks.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'opf_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_epub3_item_cover(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'epub3_cover.epub')
        book = epub.EpubBook()
        book.set_identifier('epub3-id')
        book.set_title('EPUB3 Cover')
        book.set_language('en')

        img = epub.EpubImage()
        img.file_name = 'images/cover.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        img.properties = 'cover-image'
        book.add_item(img)

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'epub3_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_opf_bad_item_id(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'bad_cover_id.epub')
        book = epub.EpubBook()
        book.set_identifier('bad-id')
        book.set_title('Bad Cover ID')
        book.set_language('en')

        book.add_metadata('OPF', 'meta', '', {'name': 'cover', 'content': 'nonexistent-id'})

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'bad_id_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_from_opf_meta_content(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'opf_cover.epub')
        book = epub.EpubBook()
        book.set_identifier('opf-id')
        book.set_title('OPF Cover')
        book.set_language('en')

        img = epub.EpubImage()
        img.file_name = 'images/cover.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        img.id = 'cover-img'
        book.add_item(img)

        book.add_metadata('OPF', 'meta', '', {'name': 'cover', 'content': 'cover-img'})

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text to pass.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'opf_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_cover_image_error_handling(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'cover_err.epub')
        book = epub.EpubBook()
        book.set_identifier('cover-err-id')
        book.set_title('Cover Err Book')
        book.set_language('en')

        img = epub.EpubImage()
        img.file_name = 'images/bad_cover.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 50
        book.add_item(img)

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text to pass the minimum length check for chapters.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'cover_err_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_nav_skipped_in_nonspine(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'nav_skip.epub')
        book = epub.EpubBook()
        book.set_identifier('nav-skip-id')
        book.set_title('Nav Skip')
        book.set_language('en')

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text to pass.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'nav_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_short_doc_after_first(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'short_doc.epub')
        book = epub.EpubBook()
        book.set_identifier('short-doc-id')
        book.set_title('Short Doc')
        book.set_language('en')

        long = epub.EpubHtml(title='Long', file_name='long.xhtml', lang='en')
        long.content = b'<html><body><p>' + b'word ' * 30 + b'</p></body></html>'
        book.add_item(long)

        short = epub.EpubHtml(title='Short', file_name='short.xhtml', lang='en')
        short.content = b'<p>X</p>'
        book.add_item(short)

        book.toc = [epub.Link('long.xhtml', 'Long', 'long'),
                    epub.Link('short.xhtml', 'Short', 'short')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [long, short]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'short_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_image_src_full_path(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_remap.epub')
        book = epub.EpubBook()
        book.set_identifier('img-remap-id')
        book.set_title('Img Remap')
        book.set_language('en')

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><img src="../images/photo.jpg"/><p>Content with enough text.</p></body></html>'
        book.add_item(c)

        img = epub.EpubImage()
        img.file_name = 'images/photo.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 50
        book.add_item(img)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'remap_out')
        result = process_epub(epub_path, out_dir)
        assert 'images/photo.jpg' in result.spine[0].content

    def test_no_body_uses_soup(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'nobody.epub')
        book = epub.EpubBook()
        book.set_identifier('nobody-id')
        book.set_title('NoBody')
        book.set_language('en')

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<div><p>No body tag but enough content to pass.</p></div>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'nobody_out')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_image_path_normalization(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_test.epub')
        book = epub.EpubBook()
        book.set_identifier('img-test')
        book.set_title('Image Test')
        book.set_language('en')

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><img src="../images/test.jpg"/><p>Content here.</p></body></html>'
        book.add_item(c)

        img = epub.EpubImage()
        img.file_name = 'images/test.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 50
        book.add_item(img)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'img_output')
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) == 1
        assert 'images/test.jpg' in result.spine[0].content

    def test_image_write_error(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'img_err.epub')
        book = epub.EpubBook()
        book.set_identifier('img-err-id')
        book.set_title('Image Error')
        book.set_language('en')

        img = epub.EpubImage()
        img.file_name = 'images/test.jpg'
        img.media_type = 'image/jpeg'
        img.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        book.add_item(img)

        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content with enough text.</p></body></html>'
        book.add_item(c)

        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        out_dir = os.path.join(tmp_dir, 'img_err_out')
        os.makedirs(out_dir, exist_ok=True)
        result = process_epub(epub_path, out_dir)
        assert len(result.spine) >= 1

    def test_chapter_error_continues(self, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'ch_err.epub')
        book = epub.EpubBook()
        book.set_identifier('ch-err-id')
        book.set_title('Chapter Error')
        book.set_language('en')

        good = epub.EpubHtml(title='Good', file_name='good.xhtml', lang='en')
        good.content = b'<html><body><p>Good chapter with enough text.</p></body></html>'
        book.add_item(good)

        bad = epub.EpubHtml(title='Bad', file_name='bad.xhtml', lang='en')
        bad.content = b'<html><body><p>Bad chapter.</p></body></html>'
        book.add_item(bad)

        book.toc = [epub.Link('good.xhtml', 'Good', 'good'), epub.Link('bad.xhtml', 'Bad', 'bad')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [good, bad]
        epub.write_epub(epub_path, book, {})

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
            ['uv', 'run', 'python', 'reader3.py'],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )
        assert result.returncode == 1
        assert 'Usage' in result.stdout

    def test_cli_nonexistent_file(self):
        result = subprocess.run(
            ['uv', 'run', 'python', 'reader3.py', '/nonexistent/file.epub'],
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
        book = epub.EpubBook()
        book.set_identifier('cli-id')
        book.set_title('CLI Test')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>CLI test content.</p></body></html>'
        book.add_item(c)
        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

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
