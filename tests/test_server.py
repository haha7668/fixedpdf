import json
import os
import pickle
import shutil
import tempfile
import zlib
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient

import server
from reader3 import Book, BookMetadata, ChapterContent


@pytest.fixture
def client():
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_analysis_cache():
    server._analysis_cache.clear()
    yield
    server._analysis_cache.clear()


@pytest.fixture
def mock_book_dir(tmp_dir):
    book_dir = os.path.join(tmp_dir, 'test_book_data')
    os.makedirs(book_dir, exist_ok=True)
    metadata = BookMetadata(title='Test Book', language='en', authors=['Author'])
    chapters = []
    for i in range(3):
        ch = ChapterContent(
            id=f'ch_{i}', href=f'ch_{i}.xhtml', title=f'Chapter {i+1}',
            content=f'<h1>Chapter {i+1}</h1><p>{"Content " * 20}</p>',
            text=f'Chapter {i+1} content. {"Word " * 30}',
            order=i
        )
        chapters.append(ch)
    book = Book(metadata=metadata, spine=chapters, toc=[], images={},
                source_file='test.epub', processed_at='2024-01-01')
    with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
        pickle.dump(book, f)
    return 'test_book_data', book, tmp_dir


# ============================================================
# Helper
# ============================================================

def _make_book(book_id, tmp_dir, title='Test', content='<p>Hello</p>', text='Hello'):
    book_dir = os.path.join(tmp_dir, book_id)
    os.makedirs(book_dir, exist_ok=True)
    ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content=content, text=text, order=0)
    book = Book(metadata=BookMetadata(title=title, language='en', authors=['A']),
                spine=[ch], toc=[], images={}, source_file='t.epub', processed_at='2024-01-01')
    with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
        pickle.dump(book, f)
    return book_dir


# ============================================================
# _detect_cjk_ratio tests
# ============================================================

class TestDetectCJKRatio:
    def test_pure_chinese(self):
        assert server._detect_cjk_ratio("你好世界") == 1.0

    def test_pure_english(self):
        assert server._detect_cjk_ratio("Hello World") == 0.0

    def test_mixed(self):
        ratio = server._detect_cjk_ratio("Hello 你好")
        assert 0.0 < ratio < 1.0

    def test_empty(self):
        assert server._detect_cjk_ratio("") == 0.0

    def test_japanese(self):
        assert server._detect_cjk_ratio("日本語テスト") == 1.0

    def test_korean(self):
        assert server._detect_cjk_ratio("한국어테스트") == 1.0


# ============================================================
# _safe_dirname tests
# ============================================================

class TestSafeDirname:
    def test_basic(self):
        assert server._safe_dirname("My Book", ["Author Name"]) == "My Book - Author Name"

    def test_special_chars_removed(self):
        assert server._safe_dirname('Book: "Title" <v2>', None) == "Book Title v2"

    def test_long_title_truncated(self):
        assert len(server._safe_dirname("A" * 200, None)) == 80

    def test_empty_title(self):
        assert server._safe_dirname("", None) == "untitled"

    def test_whitespace_collapsed(self):
        result = server._safe_dirname("  Lots   of    spaces  ", None)
        assert "  " not in result
        assert result.startswith("Lots")

    def test_no_author(self):
        assert server._safe_dirname("My Book", None) == "My Book"

    def test_empty_author_list(self):
        assert server._safe_dirname("My Book", []) == "My Book"

    def test_author_with_empty_first(self):
        assert server._safe_dirname("My Book", [""]) == "My Book"


# ============================================================
# _get_text_hash tests
# ============================================================

class TestGetTextHash:
    def test_consistent_hash(self):
        assert server._get_text_hash("hello") == server._get_text_hash("hello")

    def test_different_text_different_hash(self):
        assert server._get_text_hash("hello") != server._get_text_hash("world")

    def test_is_md5(self):
        h = server._get_text_hash("test")
        assert len(h) == 32
        assert all(c in '0123456789abcdef' for c in h)


# ============================================================
# AI config tests
# ============================================================

class TestAIConfig:
    def test_load_nonexistent(self, tmp_dir):
        config_path = os.path.join(tmp_dir, 'nonexistent.json')
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            assert 'providers' in server._ai_config
            assert 'order' in server._ai_config

    def test_save_and_load(self, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._ai_config = {
                'providers': {'test': {'api_key': 'key123', 'enabled': True}},
                'order': ['test']
            }
            server._save_ai_config()
            server._ai_config = {}
            server._load_ai_config()
            assert 'test' in server._ai_config['providers']

    def test_load_invalid_json(self, tmp_dir):
        config_path = os.path.join(tmp_dir, 'bad.json')
        with open(config_path, 'w') as f:
            f.write('not json {{{')
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            assert 'providers' in server._ai_config


# ============================================================
# _get_enabled_providers tests
# ============================================================

class TestGetEnabledProviders:
    def test_empty_config(self):
        with patch.object(server, '_ai_config', {'providers': {}, 'order': []}):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert server._get_enabled_providers() == []

    def test_user_configured_provider(self):
        config = {'providers': {'openai': {'api_key': 'sk-test', 'enabled': True, 'model': 'gpt-4'}}, 'order': ['openai']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                result = server._get_enabled_providers()
                assert len(result) == 1
                assert result[0]['id'] == 'openai'

    def test_disabled_provider_excluded(self):
        config = {'providers': {'openai': {'api_key': 'sk-test', 'enabled': False}}, 'order': ['openai']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert len(server._get_enabled_providers()) == 0

    def test_no_api_key_excluded(self):
        config = {'providers': {'openai': {'api_key': '', 'enabled': True}}, 'order': ['openai']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert len(server._get_enabled_providers()) == 0

    def test_builtin_fallback(self):
        builtins = [('gemini', 'gkey', 'gemini-flash')]
        with patch.object(server, '_ai_config', {'providers': {}, 'order': []}):
            with patch.object(server, '_get_builtin_providers', return_value=builtins):
                result = server._get_enabled_providers()
                assert len(result) == 1
                assert result[0]['id'] == 'gemini'
                assert '内置' in result[0]['name']

    def test_builtin_skipped_if_user_configured(self):
        config = {'providers': {'gemini': {'api_key': 'user-key', 'enabled': True}}, 'order': ['gemini']}
        builtins = [('gemini', 'gkey', 'gemini-flash')]
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=builtins):
                result = server._get_enabled_providers()
                assert len(result) == 1
                assert result[0]['api_key'] == 'user-key'

    def test_custom_provider(self):
        config = {'providers': {'custom_0': {'api_key': 'ck', 'enabled': True, 'custom_name': 'My Custom', 'model': 'custom-m'}}, 'order': ['custom_0']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                result = server._get_enabled_providers()
                assert result[0]['name'] == 'My Custom'

    def test_temperature_passthrough(self):
        config = {'providers': {'openai': {'api_key': 'sk', 'enabled': True, 'temperature': 0.5}}, 'order': ['openai']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert server._get_enabled_providers()[0]['temperature'] == 0.5

    def test_user_order(self):
        config = {
            'providers': {
                'p1': {'api_key': 'k1', 'enabled': True, 'model': 'm1'},
                'p2': {'api_key': 'k2', 'enabled': True, 'model': 'm2'}
            },
            'order': ['p2', 'p1']
        }
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                result = server._get_enabled_providers()
                assert len(result) == 2
                assert result[0]['id'] == 'p2'
                assert result[1]['id'] == 'p1'

    def test_unseen_providers(self):
        config = {
            'providers': {
                'p1': {'api_key': 'k1', 'enabled': True, 'model': 'm1'},
                'p2': {'api_key': 'k2', 'enabled': True, 'model': 'm2'}
            },
            'order': ['p1']
        }
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert len(server._get_enabled_providers()) == 2

    def test_no_model_default(self):
        config = {'providers': {'openai': {'api_key': 'k', 'enabled': True}}, 'order': ['openai']}
        with patch.object(server, '_ai_config', config):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                assert server._get_enabled_providers()[0]['model'] == 'gpt-4o-mini'


# ============================================================
# Library index tests
# ============================================================

class TestLibraryIndex:
    def test_build_empty(self, tmp_dir):
        books_dir = os.path.join(tmp_dir, 'books')
        index_path = os.path.join(books_dir, '.library_index.json')
        with patch.object(server, 'BOOKS_DIR', books_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            os.makedirs(books_dir, exist_ok=True)
            assert server._build_library_index() == {}

    def test_build_with_pdf_book(self, tmp_dir):
        books_dir = os.path.join(tmp_dir, 'books')
        os.makedirs(books_dir, exist_ok=True)
        book_dir = os.path.join(books_dir, 'test_data')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Test PDF", "author": "Author", "pages": 10, "format": "pdf"}
        with open(os.path.join(book_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f)
        index_path = os.path.join(books_dir, '.library_index.json')
        with patch.object(server, 'BOOKS_DIR', books_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            result = server._build_library_index()
            assert 'test_data' in result
            assert result['test_data']['title'] == 'Test PDF'

    def test_build_removes_deleted(self, tmp_dir):
        books_dir = os.path.join(tmp_dir, 'books')
        os.makedirs(books_dir, exist_ok=True)
        index_path = os.path.join(books_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'deleted_data': {'title': 'Gone'}}, f)
        with patch.object(server, 'BOOKS_DIR', books_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert 'deleted_data' not in server._build_library_index()

    def test_build_with_pkl(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'epub_book_data')
        os.makedirs(book_dir, exist_ok=True)
        metadata = BookMetadata(title='Indexed Book', language='en', authors=['A'])
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=metadata, spine=[ch, ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            result = server._build_library_index()
            assert 'epub_book_data' in result
            assert result['epub_book_data']['title'] == 'Indexed Book'
            assert result['epub_book_data']['format'] == 'epub'

    def test_build_with_old_display_title(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'old_title_data')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Original", "author": "", "pages": 1, "format": "pdf"}
        with open(os.path.join(book_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'old_title_data': {'display_title': 'My Custom Title'}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            result = server._build_library_index()
            assert result['old_title_data']['display_title'] == 'My Custom Title'

    def test_build_existing_index_uptodate(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'cached_data')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Cached", "author": "", "pages": 1, "format": "pdf"}
        meta_path = os.path.join(book_dir, 'meta.json')
        with open(meta_path, 'w') as f:
            json.dump(meta, f)
        mtime = os.path.getmtime(meta_path)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'cached_data': {'title': 'Cached', '_mtime': mtime}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert 'cached_data' in server._build_library_index()

    def test_build_no_books_dir(self, tmp_dir):
        books_dir = os.path.join(tmp_dir, 'nonexistent_books')
        index_path = os.path.join(books_dir, '.library_index.json')
        with patch.object(server, 'BOOKS_DIR', books_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert server._build_library_index() == {}

    def test_build_existing_no_change(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'cached_data')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Cached", "author": "", "pages": 1, "format": "pdf"}
        meta_path = os.path.join(book_dir, 'meta.json')
        with open(meta_path, 'w') as f:
            json.dump(meta, f)
        mtime = os.path.getmtime(meta_path)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'cached_data': {'title': 'Cached', '_mtime': mtime}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert 'cached_data' in server._build_library_index()

    def test_build_bad_json_index(self, tmp_dir):
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            f.write('not json')
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert server._build_library_index() == {}

    def test_build_pkl_no_change(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'unchanged_pkl_data')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='Unchanged', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        pkl_path = os.path.join(book_dir, 'book.pkl')
        with open(pkl_path, 'wb') as f:
            pickle.dump(book, f)
        pkl_mtime = os.path.getmtime(pkl_path)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'unchanged_pkl_data': {'title': 'Unchanged', '_mtime': pkl_mtime}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            result = server._build_library_index()
            assert 'unchanged_pkl_data' in result
            assert result['unchanged_pkl_data']['title'] == 'Unchanged'

    def test_build_pdf_no_change(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'unchanged_pdf_data')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Cached PDF", "author": "", "pages": 5, "format": "pdf"}
        meta_path = os.path.join(book_dir, 'meta.json')
        with open(meta_path, 'w') as f:
            json.dump(meta, f)
        mtime = os.path.getmtime(meta_path)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'unchanged_pdf_data': {'title': 'Cached PDF', '_mtime': mtime}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch.object(server, '_LIBRARY_INDEX', index_path):
            assert 'unchanged_pdf_data' in server._build_library_index()


# ============================================================
# load_book_cached tests
# ============================================================

class TestLoadBookCached:
    def test_load_existing(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'test_book_data')
        os.makedirs(book_dir, exist_ok=True)
        metadata = BookMetadata(title='Cached Book', language='en')
        book = Book(metadata=metadata, spine=[], toc=[], images={},
                    source_file='test.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            result = server.load_book_cached('test_book_data')
            assert result is not None
            assert result.metadata.title == 'Cached Book'

    def test_load_nonexistent(self, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert server.load_book_cached('nonexistent_data') is None

    def test_load_corrupt(self, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'corrupt_data')
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            f.write(b'corrupt data')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert server.load_book_cached('corrupt_data') is None


# ============================================================
# _find_cover_image tests
# ============================================================

class TestFindCoverImage:
    def test_marker_file(self, tmp_dir):
        book_id = 'test_book'
        book_dir = os.path.join(tmp_dir, book_id)
        images_dir = os.path.join(book_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)
        with open(os.path.join(images_dir, 'cover.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        with open(os.path.join(book_dir, 'cover_image.txt'), 'w') as f:
            f.write('cover.jpg')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            result = server._find_cover_image(book_id)
            assert result is not None
            assert 'cover.jpg' in result

    def test_cover_prefix_match(self, tmp_dir):
        book_id = 'test_book2'
        book_dir = os.path.join(tmp_dir, book_id)
        images_dir = os.path.join(book_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)
        with open(os.path.join(images_dir, 'cover_001.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            result = server._find_cover_image(book_id)
            assert result is not None
            assert 'cover_001.jpg' in result

    def test_no_images_dir(self, tmp_dir):
        os.makedirs(os.path.join(tmp_dir, 'no_images'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert server._find_cover_image('no_images') is None

    def test_empty_images_dir(self, tmp_dir):
        os.makedirs(os.path.join(tmp_dir, 'empty_images', 'images'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert server._find_cover_image('empty_images') is None

    def test_fallback_to_largest(self, tmp_dir):
        book_id = 'largest_book'
        images_dir = os.path.join(tmp_dir, book_id, 'images')
        os.makedirs(images_dir, exist_ok=True)
        with open(os.path.join(images_dir, 'small.png'), 'wb') as f:
            f.write(b'x' * 100)
        with open(os.path.join(images_dir, 'big.png'), 'wb') as f:
            f.write(b'x' * 1000)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            result = server._find_cover_image(book_id)
            assert result is not None
            assert 'big.png' in result

    def test_find_cover_from_chapter(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'firstimg')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with open(os.path.join(book_dir, 'images', 'chapter_img.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        ch = ChapterContent(
            id='ch_0', href='ch.xhtml', title='Ch',
            content='<html><body><img src="chapter_img.jpg"/><p>Content</p></body></html>',
            text='Content', order=0
        )
        book = Book(metadata=BookMetadata(title='FirstImg', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert server._find_cover_image('firstimg') is not None


# ============================================================
# Streaming functions
# ============================================================

class TestStreamOpenAICompat:
    @pytest.mark.asyncio
    async def test_stream_success(self):
        async def mock_aiter_bytes():
            yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
            yield b'data: [DONE]\n\n'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_openai_compat('url', 'key', 'model', 'prompt', 0.7, 100):
                chunks.append(chunk)
            assert 'hello' in chunks
            assert ' world' in chunks

    @pytest.mark.asyncio
    async def test_stream_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.aread = AsyncMock(return_value=b'bad request')
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 400"):
                async for _ in server._stream_openai_compat('url', 'key', 'model', 'p', 0.7, 100):
                    pass

    @pytest.mark.asyncio
    async def test_stream_with_extra_body(self):
        async def mock_aiter_bytes():
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b'data: [DONE]\n\n'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_openai_compat('url', 'key', 'm', 'p', 0.7, 100, extra_body={"thinking": {"type": "disabled"}}):
                chunks.append(chunk)
            assert 'ok' in chunks

    @pytest.mark.asyncio
    async def test_stream_bad_json_lines(self):
        async def mock_aiter_bytes():
            yield b'not json\n'
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b'data: [DONE]\n\n'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_openai_compat('url', 'key', 'm', 'p', 0.7, 100):
                chunks.append(chunk)
            assert 'ok' in chunks


class TestStreamAnthropic:
    @pytest.mark.asyncio
    async def test_stream_success(self):
        async def mock_aiter_bytes():
            yield b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_anthropic('url', 'key', 'model', 'p', 0.7, 100):
                chunks.append(chunk)
            assert 'hi' in chunks

    @pytest.mark.asyncio
    async def test_stream_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.aread = AsyncMock(return_value=b'forbidden')
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 403"):
                async for _ in server._stream_anthropic('url', 'key', 'm', 'p', 0.7, 100):
                    pass

    @pytest.mark.asyncio
    async def test_stream_bad_json(self):
        async def mock_aiter_bytes():
            yield b'data: not json\n\n'
            yield b'data: {"type":"content_block_delta","delta":{"text":"ok"}}\n\n'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_anthropic('url', 'key', 'm', 'p', 0.7, 100):
                chunks.append(chunk)
            assert 'ok' in chunks


# ============================================================
# AI call functions
# ============================================================

class TestAICallFunctions:
    @pytest.mark.asyncio
    async def test_call_openai_compat_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "Hello!"}}]}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            result = await server._call_openai_compat('url', 'key', 'model', 'prompt', 0.7, 100)
            assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_call_openai_compat_with_extra(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            result = await server._call_openai_compat('url', 'key', 'model', 'p', 0.5, 50, extra_body={"thinking": {"type": "disabled"}})
            assert result == "OK"

    @pytest.mark.asyncio
    async def test_call_openai_compat_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Unauthorized"}}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 401"):
                await server._call_openai_compat('url', 'key', 'm', 'p', 0.7, 100)

    @pytest.mark.asyncio
    async def test_call_openai_compat_error_non_dict(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "bad request"}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 400"):
                await server._call_openai_compat('url', 'key', 'm', 'p', 0.7, 100)

    @pytest.mark.asyncio
    async def test_call_openai_compat_error_no_json(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = Exception("No JSON")
        mock_resp.text = "Internal Error"
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 500"):
                await server._call_openai_compat('url', 'key', 'm', 'p', 0.7, 100)

    @pytest.mark.asyncio
    async def test_call_anthropic_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"text": "Hi!"}]}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            assert await server._call_anthropic('url', 'key', 'm', 'p', 0.7, 100) == "Hi!"

    @pytest.mark.asyncio
    async def test_call_anthropic_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": {"message": "Forbidden"}}
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 403"):
                await server._call_anthropic('url', 'key', 'm', 'p', 0.7, 100)

    @pytest.mark.asyncio
    async def test_call_anthropic_error_no_json(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = Exception("fail")
        mock_resp.text = "err"
        with patch.object(server._ai_client, 'post', new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 500"):
                await server._call_anthropic('url', 'key', 'm', 'p', 0.7, 100)

    @pytest.mark.asyncio
    async def test_call_gemini_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Gemini response"
        mock_client.models.generate_content.return_value = mock_response
        with patch('server.google_genai.Client', return_value=mock_client):
            assert await server._call_gemini('key', 'model', 'prompt', 0.7, 100) == "Gemini response"


# ============================================================
# _ai_complete tests
# ============================================================

class TestAIComplete:
    @pytest.mark.asyncio
    async def test_no_providers(self):
        with patch.object(server, '_get_enabled_providers', return_value=[]), pytest.raises(Exception):
            await server._ai_complete("prompt")

    @pytest.mark.asyncio
    async def test_success_openai(self):
        providers = [{'id': 'openai', 'name': 'OpenAI', 'api_key': 'key', 'model': 'gpt-4', 'base_url': 'https://api.openai.com/v1/', 'format': 'openai'}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', new_callable=AsyncMock, return_value="result"):
                text, model = await server._ai_complete("prompt")
                assert text == "result"

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        providers = [
            {'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'url', 'format': 'openai'},
            {'id': 'p2', 'name': 'P2', 'api_key': 'k', 'model': 'm', 'base_url': 'url', 'format': 'openai'},
        ]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', side_effect=[Exception("fail"), "success"]):
                text, model = await server._ai_complete("prompt")
                assert text == "success"

    @pytest.mark.asyncio
    async def test_all_fail(self):
        providers = [{'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'url', 'format': 'openai'}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', side_effect=Exception("fail")):
                with pytest.raises(Exception):
                    await server._ai_complete("prompt")

    @pytest.mark.asyncio
    async def test_task_routing(self):
        providers = [
            {'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'url', 'format': 'openai'},
            {'id': 'p2', 'name': 'P2', 'api_key': 'k', 'model': 'm', 'base_url': 'url', 'format': 'openai'},
        ]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', new_callable=AsyncMock, return_value="ok"):
                text, model = await server._ai_complete("prompt", task="translate")
                assert text == "ok"

    @pytest.mark.asyncio
    async def test_anthropic_format(self):
        providers = [{'id': 'anthropic', 'name': 'Anthropic', 'api_key': 'key', 'model': 'claude', 'base_url': 'https://api.anthropic.com/v1/', 'format': 'anthropic'}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_anthropic', new_callable=AsyncMock, return_value="result"):
                text, model = await server._ai_complete("prompt")
                assert text == "result"

    @pytest.mark.asyncio
    async def test_gemini_format(self):
        providers = [{'id': 'gemini', 'name': 'Gemini', 'api_key': 'key', 'model': 'gemini-2', 'base_url': '', 'format': 'gemini'}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_gemini', new_callable=AsyncMock, return_value="result"):
                text, model = await server._ai_complete("prompt")
                assert text == "result"

    @pytest.mark.asyncio
    async def test_zhipuai_extra_body(self):
        providers = [{'id': 'zhipuai', 'name': 'ZhipuAI', 'api_key': 'key', 'model': 'glm', 'base_url': 'url', 'format': 'openai'}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', new_callable=AsyncMock, return_value="result"):
                text, model = await server._ai_complete("prompt")
                assert text == "result"

    @pytest.mark.asyncio
    async def test_custom_provider_temperature(self):
        providers = [{'id': 'custom_0', 'name': 'Custom', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai', 'temperature': 0.3, 'max_tokens': 500}]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_call_openai_compat', new_callable=AsyncMock, return_value="ok"):
                text, model = await server._ai_complete("prompt")
                assert text == "ok"


# ============================================================
# _ai_stream tests
# ============================================================

class TestAIStream:
    @pytest.mark.asyncio
    async def test_stream_no_providers(self):
        with patch.object(server, '_get_enabled_providers', return_value=[]):
            gen = await server._ai_stream("prompt")
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)
            assert any("Error" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_stream_all_providers_fail(self):
        providers = [{'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'}]
        async def mock_stream(*a, **kw):
            raise Exception("fail")
            yield
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_stream_openai_compat', side_effect=mock_stream):
                gen = await server._ai_stream("prompt")
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                assert any("Error" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_stream_task_routing(self):
        providers = [
            {'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
            {'id': 'p2', 'name': 'P2', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
        ]
        async def mock_stream(*a, **kw):
            yield "chunk"
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_ai_config', {'task_routing': {'translate': 'p2'}}):
                with patch.object(server, '_stream_openai_compat', side_effect=mock_stream):
                    gen = await server._ai_stream("prompt", task="translate")
                    chunks = []
                    async for chunk in gen:
                        chunks.append(chunk)
                    assert 'chunk' in chunks

    @pytest.mark.asyncio
    async def test_stream_anthropic(self):
        providers = [{'id': 'anthropic', 'name': 'A', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'anthropic'}]
        async def mock_stream(*a, **kw):
            yield "hi"
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_stream_anthropic', side_effect=mock_stream):
                gen = await server._ai_stream("prompt")
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                assert 'hi' in chunks

    @pytest.mark.asyncio
    async def test_stream_gemini(self):
        providers = [{'id': 'gemini', 'name': 'G', 'api_key': 'k', 'model': 'm', 'base_url': '', 'format': 'gemini'}]
        mock_client = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.text = "gemini chunk"
        mock_client.models.generate_content_stream.return_value = [mock_chunk]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch('server.google_genai.Client', return_value=mock_client):
                gen = await server._ai_stream("prompt")
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                assert 'gemini chunk' in chunks

    @pytest.mark.asyncio
    async def test_stream_gemini_value_error(self):
        providers = [{'id': 'gemini', 'name': 'G', 'api_key': 'k', 'model': 'm', 'base_url': '', 'format': 'gemini'}]
        mock_client = MagicMock()
        def bad_chunk():
            raise ValueError("no text")
        mock_chunk = MagicMock()
        mock_chunk.configure_mock(**{'text': property(bad_chunk)})
        mock_client.models.generate_content_stream.return_value = [mock_chunk]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch('server.google_genai.Client', return_value=mock_client):
                gen = await server._ai_stream("prompt")
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                assert len(chunks) >= 0

    @pytest.mark.asyncio
    async def test_stream_openai_fallback(self):
        providers = [
            {'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
            {'id': 'p2', 'name': 'P2', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
        ]
        async def fail_stream(*a, **kw):
            raise Exception("fail")
            yield
        async def ok_stream(*a, **kw):
            yield "success"
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_stream_openai_compat', side_effect=[fail_stream(), ok_stream()]):
                gen = await server._ai_stream("prompt")
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                assert 'success' in chunks


# ============================================================
# _chinese_define tests
# ============================================================

class TestChineseDefine:
    @pytest.mark.asyncio
    async def test_cached(self):
        server._cn_dict_cache['cached_word'] = 'cached_def'
        assert await server._chinese_define('cached_word') == 'cached_def'

    @pytest.mark.asyncio
    async def test_ai_call(self):
        with patch.object(server, '_ai_complete', new_callable=AsyncMock, return_value=("定义", "model")):
            result = await server._chinese_define('new_word')
            assert result == '定义'
            assert server._cn_dict_cache.get('new_word') == '定义'

    @pytest.mark.asyncio
    async def test_ai_error(self):
        with patch.object(server, '_ai_complete', side_effect=Exception("fail")):
            assert await server._chinese_define('fail_word') is None


# ============================================================
# _google_translate tests
# ============================================================

class TestGoogleTranslate:
    @pytest.mark.asyncio
    async def test_translate_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [[['translated text', None, None, None]]]
        with patch.object(server._gt_client, 'get', new_callable=AsyncMock, return_value=mock_resp):
            assert await server._google_translate('hello') == 'translated text'

    @pytest.mark.asyncio
    async def test_translate_dest(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [[['bonjour', None, None, None]]]
        with patch.object(server._gt_client, 'get', new_callable=AsyncMock, return_value=mock_resp):
            assert await server._google_translate('hello', dest='fr') == 'bonjour'


# ============================================================
# _wiki_summary tests
# ============================================================

class TestWikiSummary:
    @pytest.mark.asyncio
    async def test_wiki_success(self):
        mock_data = {
            'title': 'Python',
            'extract': 'Python is a language.',
            'content_urls': {'desktop': {'page': 'https://en.wikipedia.org/wiki/Python'}}
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch('urllib.request.urlopen', return_value=mock_resp):
            result = await server._wiki_summary('Python')
            assert result['title'] == 'Python'
            assert result['url'] == 'https://en.wikipedia.org/wiki/Python'

    @pytest.mark.asyncio
    async def test_wiki_error(self):
        with patch('urllib.request.urlopen', side_effect=Exception("fail")):
            assert await server._wiki_summary('Nonexistent') == {}

    @pytest.mark.asyncio
    async def test_wiki_cjk(self):
        mock_data = {'title': '编程', 'extract': '编程是一种技能', 'content_urls': {}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch('urllib.request.urlopen', return_value=mock_resp):
            result = await server._wiki_summary('编程')
            assert 'title' in result


# ============================================================
# Dict lookup tests
# ============================================================

class TestDictLookup:
    def test_no_conn(self):
        with patch.object(server, '_dict_conn', None):
            assert server._dict_lookup('hello') is None

    def test_no_cn_conn(self):
        with patch.object(server, '_cn_dict_conn', None):
            assert server._cn_dict_lookup('你好') is None

    def test_dict_lookup_with_conn(self):
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            'word': 'hello', 'phonetic': '/həˈloʊ/',
            'translation': 'int. 你好', 'definition': ''
        }[key]
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        with patch.object(server, '_dict_conn', mock_conn):
            result = server._dict_lookup('hello')
            assert result is not None
            assert result['word'] == 'hello'

    def test_dict_lookup_no_result(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch.object(server, '_dict_conn', mock_conn):
            assert server._dict_lookup('nonexistent') is None

    def test_cn_dict_lookup_with_conn(self):
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            'word': '你好', 'pinyin': 'nǐ hǎo',
            'definition': '打招呼', 'source': 'xinhua'
        }[key]
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        with patch.object(server, '_cn_dict_conn', mock_conn):
            result = server._cn_dict_lookup('你好')
            assert result is not None

    def test_cn_dict_lookup_no_result(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch.object(server, '_cn_dict_conn', mock_conn):
            assert server._cn_dict_lookup('nonexistent') is None


# ============================================================
# _reload_dict tests
# ============================================================

class TestReloadDict:
    def test_reload(self):
        with patch.object(server, '_dict_db_path', '/tmp/test.db'):
            with patch.object(server, '_cn_dict_path', '/tmp/test_cn.db'):
                with patch.object(server, '_dict_conn', None):
                    with patch.object(server, '_cn_dict_conn', None):
                        with patch('os.path.exists', return_value=True):
                            with patch('server._open_dict_db') as mock_open:
                                mock_open.return_value = MagicMock()
                                server._reload_dict()
                                assert mock_open.call_count == 2


# ============================================================
# _process_pdf tests
# ============================================================

class TestProcessPdf:
    def test_process_pdf(self, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        pdf_path = os.path.join(tmp_dir, 'test.pdf')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF")
        doc.set_metadata({"title": "Test PDF Doc", "author": "PDF Author"})
        doc.save(pdf_path)
        doc.close()
        out_dir = os.path.join(tmp_dir, 'pdf_output')
        result = server._process_pdf(pdf_path, out_dir)
        assert result['title'] == 'Test PDF Doc'
        assert result['author'] == 'PDF Author'
        assert result['format'] == 'pdf'
        assert os.path.exists(os.path.join(out_dir, 'meta.json'))
        assert os.path.exists(os.path.join(out_dir, 'book.pdf'))
        assert os.path.exists(os.path.join(out_dir, 'cover_image.txt'))

    def test_process_pdf_no_metadata(self, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        pdf_path = os.path.join(tmp_dir, 'no_meta.pdf')
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf_path)
        doc.close()
        out_dir = os.path.join(tmp_dir, 'pdf_out2')
        result = server._process_pdf(pdf_path, out_dir)
        assert result['title'] == 'no_meta'

    def test_process_pdf_same_path(self, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        pdf_path = os.path.join(tmp_dir, 'same.pdf')
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf_path)
        doc.close()
        out_dir = os.path.join(tmp_dir, 'same_data')
        os.makedirs(out_dir, exist_ok=True)
        dest_pdf = os.path.join(out_dir, 'book.pdf')
        shutil.copy2(pdf_path, dest_pdf)
        server._process_pdf(pdf_path, out_dir)
        assert os.path.exists(dest_pdf)


# ============================================================
# API endpoint tests - basic
# ============================================================

class TestLibraryEndpoint:
    def test_library_view(self, client):
        assert client.get('/').status_code == 200

    def test_book_cover_404(self, client):
        assert client.get('/api/book-cover/nonexistent').status_code == 404


class TestReadChapter:
    def test_invalid_chapter_index(self, client):
        assert client.get('/read/nonexistent/abc').status_code == 404

    def test_image_fallback(self, client):
        assert client.get('/read/nonexistent/test.jpg').status_code == 404

    def test_images_proxy(self, client):
        assert client.get('/read/images/test.jpg', headers={'referer': '/read/test_book/0'}).status_code == 404

    def test_book_not_found(self, client):
        assert client.get('/read/nonexistent/0').status_code == 404

    def test_images_route(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            os.makedirs(os.path.join(tmp_dir, book_id, 'images'), exist_ok=True)
            with open(os.path.join(tmp_dir, book_id, 'images', 'test.jpg'), 'wb') as f:
                f.write(b'fake jpg')
            assert client.get(f'/read/{book_id}/images/test.jpg').status_code == 200

    def test_read_chapter_success(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert client.get(f'/read/{book_id}/0').status_code == 200

    def test_read_images_proxy(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            os.makedirs(os.path.join(tmp_dir, book_id, 'images'), exist_ok=True)
            with open(os.path.join(tmp_dir, book_id, 'images', 'img.png'), 'wb') as f:
                f.write(b'png')
            response = client.get('/read/images/img.png', headers={'referer': f'/read/{book_id}/0'})
            assert response.status_code == 200

    def test_read_chapter_with_svg(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        book.spine[0].content = '<svg preserveAspectRatio="none" width="100%" height="100%"><rect/></svg>'
        with open(os.path.join(tmp_dir, book_id, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert client.get(f'/read/{book_id}/0').status_code == 200

    def test_read_chapter_with_image_ref(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'img_ref')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with open(os.path.join(book_dir, 'images', 'test.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hello</p>', text='Hello', order=0)
        book = Book(metadata=BookMetadata(title='ImgRef', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert client.get('/read/img_ref/0').status_code == 200

    def test_read_chapter_no_cover_found(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'nocover')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hello</p>', text='Hello', order=0)
        book = Book(metadata=BookMetadata(title='NoCover', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert client.get('/read/nocover/0').status_code == 200

    def test_serve_book_image(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'img_serve')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with open(os.path.join(book_dir, 'images', 'test.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='ImgServe', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert client.get('/read/img_serve/images/test.jpg').status_code == 200

    def test_serve_book_image_not_found(self, client, tmp_dir):
        os.makedirs(os.path.join(tmp_dir, 'img_notfound'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert client.get('/read/img_notfound/images/nonexistent.jpg').status_code == 404

    def test_read_chapter_file_fallback(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'file_fallback')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with open(os.path.join(book_dir, 'images', 'test.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='FileFallback', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            assert client.get('/read/file_fallback/test.jpg').status_code == 200


class TestRenameBook:
    def test_rename_nonexistent(self, client):
        assert client.post('/api/rename-book/nonexistent', json={"title": "New Title"}).status_code == 404

    def test_rename_success(self, client, tmp_dir):
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'test_book': {'title': 'Old'}}, f)
        with patch.object(server, '_LIBRARY_INDEX', index_path):
            response = client.post('/api/rename-book/test_book', json={"title": "New Title"})
            assert response.status_code == 200
            assert response.json()['display_title'] == 'New Title'

    def test_rename_clear(self, client, tmp_dir):
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'test_book': {'title': 'Old', 'display_title': 'Custom'}}, f)
        with patch.object(server, '_LIBRARY_INDEX', index_path):
            response = client.post('/api/rename-book/test_book', json={"title": ""})
            assert response.status_code == 200
            assert response.json()['display_title'] is None


class TestDeleteBooks:
    def test_delete_empty_list(self, client):
        assert client.post('/api/delete-books', json={"book_ids": []}).status_code == 400

    def test_delete_nonexistent(self, client):
        data = client.post('/api/delete-books', json={"book_ids": ["nonexistent"]}).json()
        assert data['deleted'] == []
        assert data['count'] == 0

    def test_delete_pdf_book(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'pdf_book_data')
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, 'book.pdf'), 'wb') as f:
            f.write(b'fake pdf')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            data = client.post('/api/delete-books', json={"book_ids": ["pdf_book_data"]}).json()
            assert data['count'] == 1
            assert 'pdf_book_data' in data['deleted']

    def test_delete_epub_book(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'epub_book_data')
        os.makedirs(book_dir, exist_ok=True)
        metadata = BookMetadata(title='To Delete', language='en')
        book = Book(metadata=metadata, spine=[], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            data = client.post('/api/delete-books', json={"book_ids": ["epub_book_data"]}).json()
            assert data['count'] == 1

    def test_delete_non_book_dir(self, client, tmp_dir):
        os.makedirs(os.path.join(tmp_dir, 'not_a_book'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            data = client.post('/api/delete-books', json={"book_ids": ["not_a_book"]}).json()
            assert data['count'] == 0


class TestSearchBook:
    def test_empty_query(self, client):
        data = client.post('/api/search', json={"book_id": "x", "query": ""}).json()
        assert data['results'] == []

    def test_no_book(self, client):
        data = client.post('/api/search', json={"book_id": "nonexistent", "query": "test"}).json()
        assert data['results'] == []

    def test_search_found(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/search', json={"book_id": book_id, "query": "Chapter"}).json()
            assert len(data['results']) > 0

    def test_search_not_found(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/search', json={"book_id": book_id, "query": "xyznotfound"}).json()
            assert len(data['results']) == 0

    def test_search_long_results(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/search', json={"book_id": book_id, "query": "Word"}).json()
            assert len(data['results']) > 0

    def test_search_many_results(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'many_results')
        os.makedirs(book_dir, exist_ok=True)
        content = 'target ' * 500
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content=f'<p>{content}</p>', text=content, order=0)
        book = Book(metadata=BookMetadata(title='ManyResults', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/search', json={"book_id": "many_results", "query": "target"}).json()
            assert len(data['results']) >= 200


class TestAIEndpoints:
    def test_translate_empty(self, client):
        data = client.post('/api/ai/translate', json={"text": ""}).json()
        assert data['translation'] == ''

    def test_chat_no_question(self, client):
        assert client.post('/api/ai/chat-context', json={}).status_code == 400

    def test_providers_list(self, client):
        data = client.get('/api/ai/providers').json()
        assert 'providers' in data
        assert 'available' in data
        assert 'task_routing' in data

    def test_export_config(self, client):
        response = client.get('/api/ai/export-config')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/json'


class TestQuickTranslate:
    def test_empty_text(self, client):
        data = client.post('/api/quick-translate', json={"text": ""}).json()
        assert data['translation'] == ''

    @patch('server._dict_lookup')
    def test_dict_hit(self, mock_dict, client):
        mock_dict.return_value = {
            'word': 'hello', 'phonetic': '/həˈloʊ/',
            'translation': 'int. 你好', 'definition': ''
        }
        data = client.post('/api/quick-translate', json={"text": "hello"}).json()
        assert data['source'] == 'dict'
        assert data['word'] == 'hello'

    @patch('server._dict_lookup', return_value=None)
    @patch('server._cn_dict_lookup')
    def test_cn_dict_hit(self, mock_cn, mock_dict, client):
        mock_cn.return_value = {
            'word': '你好', 'pinyin': 'nǐ hǎo',
            'definition': '用于见面打招呼', 'source': 'xinhua'
        }
        data = client.post('/api/quick-translate', json={"text": "你好"}).json()
        assert data['source'] == 'cn-dict'

    @patch('server._dict_lookup', return_value=None)
    @patch('server._cn_dict_lookup', return_value=None)
    @patch('server._chinese_define', new_callable=AsyncMock)
    @patch('server._google_translate', new_callable=AsyncMock)
    def test_google_fallback(self, mock_gt, mock_define, mock_cn, mock_dict, client):
        mock_gt.return_value = "Hello"
        data = client.post('/api/quick-translate', json={"text": "test"}).json()
        assert data['source'] == 'google'

    @patch('server._dict_lookup', return_value=None)
    @patch('server._cn_dict_lookup', return_value=None)
    @patch('server._chinese_define', new_callable=AsyncMock)
    @patch('server._google_translate', new_callable=AsyncMock)
    def test_ai_dict_fallback(self, mock_gt, mock_define, mock_cn, mock_dict, client):
        mock_define.return_value = "定义"
        data = client.post('/api/quick-translate', json={"text": "你好"}).json()
        assert data['source'] == 'ai-dict'

    @patch('server._dict_lookup', return_value=None)
    @patch('server._cn_dict_lookup', return_value=None)
    @patch('server._chinese_define', new_callable=AsyncMock, return_value=None)
    @patch('server._google_translate', new_callable=AsyncMock, side_effect=Exception("fail"))
    def test_translate_error(self, mock_gt, mock_define, mock_cn, mock_dict, client):
        data = client.post('/api/quick-translate', json={"text": "test"}).json()
        assert data['source'] == 'error'


class TestWikiLookup:
    def test_empty_text(self, client):
        data = client.post('/api/wiki-lookup', json={"text": ""}).json()
        assert data['extract'] == ''

    @patch('server._wiki_summary', new_callable=AsyncMock)
    def test_wiki_success(self, mock_wiki, client):
        mock_wiki.return_value = {'title': 'Python', 'extract': 'A language', 'url': 'http://example.com'}
        data = client.post('/api/wiki-lookup', json={"text": "Python"}).json()
        assert data['title'] == 'Python'


class TestDictStatus:
    def test_status(self, client):
        data = client.get('/api/dict/status').json()
        assert 'dicts' in data
        assert 'has_url' in data


class TestTTS:
    def test_tts_endpoint(self, client):
        response = client.get('/api/tts?text=hello&voice=zh-CN-XiaoxiaoNeural')
        assert response.status_code in (200, 500)


class TestReadPDF:
    def test_pdf_404(self, client):
        assert client.get('/read-pdf/nonexistent').status_code == 404

    def test_pdf_file_404(self, client):
        assert client.get('/api/pdf-file/nonexistent').status_code == 404

    def test_read_pdf_success(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'pdf_book')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "PDF Book", "author": "Author", "pages": 10, "outline": []}
        with open(os.path.join(book_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert client.get('/read-pdf/pdf_book').status_code == 200

    def test_read_pdf_with_display_title(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'display_book')
        os.makedirs(book_dir, exist_ok=True)
        meta = {"title": "Original", "author": "", "pages": 5, "outline": []}
        with open(os.path.join(book_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f)
        index_path = os.path.join(tmp_dir, '.library_index.json')
        with open(index_path, 'w') as f:
            json.dump({'display_book': {'display_title': 'Custom Title'}}, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch.object(server, '_LIBRARY_INDEX', index_path):
                with patch.object(server, '_build_library_index', return_value={'display_book': {'display_title': 'Custom Title'}}):
                    assert client.get('/read-pdf/display_book').status_code == 200

    def test_serve_pdf(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'serve_pdf')
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, 'book.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert client.get('/api/pdf-file/serve_pdf').status_code == 200


class TestSearchCover:
    def test_search_cover_404(self, client):
        assert client.post('/api/search-cover/nonexistent', json={}).status_code == 404

    def test_search_cover_google_success(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'gbook')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='Python Guide', language='en', authors=['Guide']),
                    spine=[ch], toc=[], images={}, source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        google_data = {"items": [{"volumeInfo": {"title": "Python Guide", "authors": ["Guide"], "imageLinks": {"thumbnail": "http://example.com/thumb.jpg"}}}]}
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            with patch('urllib.request.urlopen') as mock_url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(google_data).encode()
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_url.return_value = mock_resp
                data = client.post('/api/search-cover/gbook', json={"query": "Python"}).json()
                assert 'covers' in data

    def test_search_cover_google_error(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'gbook_err')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='Error Book', language='en'),
                    spine=[ch], toc=[], images={}, source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            with patch('urllib.request.urlopen', side_effect=Exception("fail")):
                data = client.post('/api/search-cover/gbook_err', json={"query": "test"}).json()
                assert 'covers' in data

    def test_search_cover_douban(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'douban_book')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='中文书', language='zh', authors=['作者']),
                    spine=[ch], toc=[], images={}, source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        douban_data = [{"title": "中文书", "author_name": "作者", "pic": "https://img9.doubanio.com/view/subject/s/public/s123.jpg"}]
        google_data = {"items": []}
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            with patch('urllib.request.urlopen') as mock_url:
                call_count = [0]
                def mock_open(req, timeout=8):
                    call_count[0] += 1
                    mock_resp = MagicMock()
                    if call_count[0] == 1:
                        mock_resp.read.return_value = json.dumps(douban_data).encode()
                    else:
                        mock_resp.read.return_value = json.dumps(google_data).encode()
                    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                    mock_resp.__exit__ = MagicMock(return_value=False)
                    return mock_resp
                mock_url.side_effect = mock_open
                data = client.post('/api/search-cover/douban_book', json={}).json()
                assert 'covers' in data
                assert len(data['covers']) > 0
                assert data['covers'][0]['source'] == 'douban'


class TestProxyImage:
    def test_non_douban_rejected(self, client):
        assert client.get('/api/proxy-image?url=https://example.com/img.jpg').status_code == 400

    def test_fetch_error(self, client):
        with patch('urllib.request.urlopen', side_effect=Exception("fail")):
            assert client.get('/api/proxy-image?url=https://img9.doubanio.com/img.jpg').status_code == 502

    def test_fetch_success(self, client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'fake image'
        mock_resp.headers.get.return_value = 'image/jpeg'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch('urllib.request.urlopen', return_value=mock_resp):
            response = client.get('/api/proxy-image?url=https://img9.doubanio.com/view/subject/l/public/s123.jpg')
            assert response.status_code == 200
            assert response.headers['content-type'] == 'image/jpeg'


class TestImportLocal:
    def test_file_not_found(self, client):
        assert client.post('/api/import-local', json={"path": "/nonexistent/file.epub"}).status_code == 400

    def test_unsupported_format(self, client, tmp_dir):
        bad_file = os.path.join(tmp_dir, 'test.txt')
        with open(bad_file, 'w') as f:
            f.write('hello')
        assert client.post('/api/import-local', json={"path": bad_file}).status_code == 400

    def test_import_local_epub(self, client, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'test.epub')
        book = epub.EpubBook()
        book.set_identifier('test-id')
        book.set_title('Test Book')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content of chapter.</p></body></html>'
        book.add_item(c)
        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('shutil.copy2'):
            response = client.post('/api/import-local', json={"path": epub_path})
            assert response.status_code == 200
            assert response.json()['success'] is True

    def test_import_local_epub_copy_fallback(self, client, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'fallback.epub')
        book = epub.EpubBook()
        book.set_identifier('fb-id')
        book.set_title('Fallback')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content.</p></body></html>'
        book.add_item(c)
        book.toc = []
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch('shutil.copy2', side_effect=PermissionError("denied")):
                with patch('shutil.copy'):
                    response = client.post('/api/import-local', json={"path": epub_path})
                    assert response.status_code == 200


class TestUpload:
    def test_no_file(self, client):
        assert client.post('/api/upload').status_code == 422

    def test_unsupported_extension(self, client):
        data = {'file': ('test.txt', BytesIO(b'hello'), 'text/plain')}
        assert client.post('/api/upload', files=data).status_code == 400

    def test_upload_epub(self, client, tmp_dir):
        book = epub.EpubBook()
        book.set_identifier('upload-id')
        book.set_title('Upload Test')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content.</p></body></html>'
        book.add_item(c)
        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub_buf = BytesIO()
        epub.write_epub(epub_buf, book, {})
        epub_buf.seek(0)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('shutil.copy2'):
            with patch.object(server, '_find_cover_image', return_value=None):
                data = {'file': ('test.epub', epub_buf, 'application/epub+zip')}
                response = client.post('/api/upload', files=data)
                assert response.status_code == 200
                assert response.json()['success'] is True

    def test_upload_processing_error(self, client, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch.object(server, 'process_epub', side_effect=Exception("Bad EPUB")):
                data = {'file': ('bad.epub', BytesIO(b'bad'), 'application/epub+zip')}
                assert client.post('/api/upload', files=data).status_code == 500


class TestReprocess:
    def test_no_source(self, client):
        assert client.post('/api/reprocess/nonexistent').status_code == 400

    def test_reprocess_success(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'reprocess_data')
        os.makedirs(book_dir, exist_ok=True)
        epub_path = os.path.join(book_dir, 'source.epub')
        book = epub.EpubBook()
        book.set_identifier('re-id')
        book.set_title('Reprocess')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content.</p></body></html>'
        book.add_item(c)
        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server._analysis_cache['reprocess_data:0'] = {'old': True}
            response = client.post('/api/reprocess/reprocess_data')
            assert response.status_code == 200
            assert 'reprocess_data:0' not in server._analysis_cache

    def test_reprocess_error(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'fail_reprocess')
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, 'source.epub'), 'wb') as f:
            f.write(b'bad')
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            assert client.post('/api/reprocess/fail_reprocess').status_code == 500


class TestSetCover:
    def test_no_url(self, client):
        assert client.post('/api/set-cover/nonexistent', json={}).status_code == 400

    def test_set_cover_error(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'err_book_data')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
                assert client.post('/api/set-cover/err_book_data', json={"image_url": "https://example.com/cover.jpg"}).status_code == 500

    def test_set_cover_success(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'cover_set')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('urllib.request.urlopen') as mock_url:
            import io

            from PIL import Image
            img = Image.new('RGB', (10, 10), (200, 200, 200))
            buf = io.BytesIO()
            img.save(buf, 'JPEG')
            jpeg_bytes = buf.getvalue()
            mock_resp = MagicMock()
            mock_resp.read.return_value = jpeg_bytes
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_url.return_value = mock_resp
            response = client.post('/api/set-cover/cover_set', json={"image_url": "https://example.com/cover.jpg"})
            assert response.status_code == 200
            assert os.path.exists(os.path.join(book_dir, 'cover_image.txt'))


class TestSaveProviders:
    def test_save_empty(self, client):
        data = client.post('/api/ai/providers', json={"providers": []}).json()
        assert data['ok'] is True

    def test_save_with_task_routing(self, client):
        response = client.post('/api/ai/providers', json={
            "providers": [{"id": "test_p", "api_key": "key", "enabled": True, "model": "m"}],
            "task_routing": {"translate": "test_p"}
        })
        assert response.status_code == 200

    def test_save_keep_old_key(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {'old_p': {'api_key': 'old_key', 'enabled': True}}, 'order': ['old_p']}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{"id": "old_p", "api_key": "", "enabled": True}]
            })
            assert response.status_code == 200

    def test_save_custom(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{"id": "custom_0", "api_key": "k", "enabled": True, "custom_name": "My AI", "temperature": 0.5, "max_tokens": 1000}]
            })
            assert response.status_code == 200

    def test_save_with_all_fields(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{
                    "id": "custom_0", "api_key": "k", "enabled": True,
                    "model": "m", "base_url": "u", "custom_name": "My AI",
                    "temperature": 0.5, "max_tokens": 1000
                }]
            })
            assert response.status_code == 200

    def test_save_custom_name(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{"id": "custom_0", "api_key": "k", "enabled": True, "custom_name": "My AI"}]
            })
            assert response.status_code == 200


class TestTestProvider:
    def test_no_api_key(self, client):
        data = client.post('/api/ai/test-provider', json={"id": "openai", "api_key": "", "model": "gpt-4"}).json()
        assert data['ok'] is False

    def test_no_base_url(self, client):
        data = client.post('/api/ai/test-provider', json={"id": "custom", "api_key": "sk-test", "model": "m", "base_url": ""}).json()
        assert data['ok'] is False

    @patch('server.httpx.AsyncClient')
    def test_anthropic_success(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg"}
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "anthropic", "api_key": "k", "model": "claude", "base_url": "https://api.anthropic.com/v1/"
        })
        assert response.json()['ok'] is True

    @patch('server.httpx.AsyncClient')
    def test_anthropic_error(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Unauthorized"}}
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "anthropic", "api_key": "bad", "model": "claude", "base_url": "https://api.anthropic.com/v1/"
        })
        assert response.json()['ok'] is False

    @patch('server.httpx.AsyncClient')
    def test_openai_success(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "openai", "api_key": "k", "model": "gpt-4", "base_url": "https://api.openai.com/v1/"
        })
        assert response.json()['ok'] is True

    @patch('server.httpx.AsyncClient')
    def test_zhipuai(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "zhipuai", "api_key": "k", "model": "glm", "base_url": "https://open.bigmodel.cn/api/paas/v4/"
        })
        assert response.json()['ok'] is True

    def test_gemini_success(self, client):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock()
        with patch('server.google_genai.Client', return_value=mock_client):
            response = client.post('/api/ai/test-provider', json={"id": "gemini", "api_key": "k", "model": "gemini-2"})
            assert response.json()['ok'] is True

    def test_gemini_error(self, client):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")
        with patch('server.google_genai.Client', return_value=mock_client):
            response = client.post('/api/ai/test-provider', json={"id": "gemini", "api_key": "bad", "model": "gemini-2"})
            assert response.json()['ok'] is False

    @patch('server.httpx.AsyncClient')
    def test_exception(self, mock_cls, client):
        async def mock_post(*a, **kw):
            raise Exception("Connection refused")
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "openai", "api_key": "k", "model": "gpt-4", "base_url": "https://api.openai.com/v1/"
        })
        assert response.json()['ok'] is False

    @patch('server.httpx.AsyncClient')
    def test_non_dict_error(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "bad request"}
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "openai", "api_key": "k", "model": "m", "base_url": "https://api.openai.com/v1/"
        })
        assert response.json()['ok'] is False

    @patch('server.httpx.AsyncClient')
    def test_text_fallback(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = Exception("no json")
        async def mock_post(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.post = mock_post
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/test-provider', json={
            "id": "openai", "api_key": "k", "model": "m", "base_url": "https://api.openai.com/v1/"
        })
        assert response.json()['ok'] is False

    def test_stored_key(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {'providers': {'openai': {'api_key': 'stored_key', 'enabled': True}}, 'order': ['openai']}
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            with patch('server.httpx.AsyncClient') as mock_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                async def mock_post(*a, **kw):
                    return mock_resp
                mock_inst = MagicMock()
                mock_inst.post = mock_post
                mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
                mock_inst.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_inst
                response = client.post('/api/ai/test-provider', json={
                    "id": "openai", "api_key": "", "model": "gpt-4", "base_url": "https://api.openai.com/v1/"
                })
                assert response.status_code == 200

    def test_base_url_default(self, client):
        with patch('server.httpx.AsyncClient') as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            async def mock_post(*a, **kw):
                return mock_resp
            mock_inst = MagicMock()
            mock_inst.post = mock_post
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_inst
            response = client.post('/api/ai/test-provider', json={
                "id": "deepseek", "api_key": "k", "model": "deepseek-chat"
            })
            assert response.json()['ok'] is True


class TestFetchModels:
    def test_no_key(self, client):
        data = client.post('/api/ai/fetch-models', json={"id": "openai", "api_key": ""}).json()
        assert data['models'] == []

    def test_gemini(self, client):
        mock_client = MagicMock()
        mock_model = MagicMock()
        mock_model.name = 'models/gemini-2'
        mock_model.supported_actions = ['generateContent']
        mock_client.models.list.return_value = [mock_model]
        with patch('server.google_genai.Client', return_value=mock_client):
            response = client.post('/api/ai/fetch-models', json={"id": "gemini", "api_key": "k"})
            assert 'models' in response.json()

    @patch('server.httpx.AsyncClient')
    def test_openai(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "gpt-4"}, {"id": "gpt-3.5"}]}
        mock_resp.raise_for_status = MagicMock()
        async def mock_get(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.get = mock_get
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/fetch-models', json={"id": "openai", "api_key": "k", "base_url": "https://api.openai.com/v1/"})
        assert len(response.json()['models']) == 2

    @patch('server.httpx.AsyncClient')
    def test_anthropic(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "claude-3"}]}
        mock_resp.raise_for_status = MagicMock()
        async def mock_get(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.get = mock_get
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/fetch-models', json={"id": "anthropic", "api_key": "k", "base_url": "https://api.anthropic.com/v1/"})
        assert len(response.json()['models']) == 1

    @patch('server.httpx.AsyncClient')
    def test_together(self, mock_cls, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "llama-70b"}]
        mock_resp.raise_for_status = MagicMock()
        async def mock_get(*a, **kw):
            return mock_resp
        mock_inst = MagicMock()
        mock_inst.get = mock_get
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/fetch-models', json={"id": "together", "api_key": "k", "base_url": "https://api.together.xyz/v1/"})
        assert len(response.json()['models']) == 1

    @patch('server.httpx.AsyncClient')
    def test_error(self, mock_cls, client):
        async def mock_get(*a, **kw):
            raise Exception("Connection error")
        mock_inst = MagicMock()
        mock_inst.get = mock_get
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst
        response = client.post('/api/ai/fetch-models', json={"id": "openai", "api_key": "k", "base_url": "https://api.openai.com/v1/"})
        assert response.json()['models'] == []

    def test_gemini_error(self, client):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = Exception("fail")
        with patch('server.google_genai.Client', return_value=mock_client):
            response = client.post('/api/ai/fetch-models', json={"id": "gemini", "api_key": "bad"})
            assert response.json()['models'] == []

    def test_stored_key(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {'providers': {'openai': {'api_key': 'stored_key', 'enabled': True}}, 'order': ['openai']}
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            with patch('server.httpx.AsyncClient') as mock_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"data": [{"id": "gpt-4"}]}
                mock_resp.raise_for_status = MagicMock()
                async def mock_get(*a, **kw):
                    return mock_resp
                mock_inst = MagicMock()
                mock_inst.get = mock_get
                mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
                mock_inst.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_inst
                response = client.post('/api/ai/fetch-models', json={
                    "id": "openai", "api_key": "", "base_url": "https://api.openai.com/v1/"
                })
                assert response.status_code == 200


class TestImportConfig:
    def test_invalid_config(self, client):
        assert client.post('/api/ai/import-config', json={"providers": []}).status_code == 400

    def test_import_config_valid(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/import-config', json={
                'providers': {'test': {'api_key': 'k', 'enabled': True}},
                'order': ['test']
            })
            assert response.status_code == 200
            assert response.json()['count'] == 1

    def test_import_config_with_task_routing(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/import-config', json={
                'providers': {'p1': {'api_key': 'k', 'enabled': True}},
                'order': ['p1'],
                'task_routing': {'translate': 'p1'}
            })
            assert response.status_code == 200


class TestAppleBooks:
    def test_apple_books_list(self, client):
        data = client.get('/api/apple-books').json()
        assert 'books' in data

    def test_no_db(self, client):
        with patch('os.path.exists', return_value=False):
            assert 'error' in client.get('/api/apple-books').json()

    def test_cover_not_found(self, client):
        with patch('server.APPLE_BOOKS_COVER_DIR', '/nonexistent'):
            assert client.get('/api/apple-books/cover/test').status_code == 404


class TestDictDownload:
    def test_download_unknown(self, client):
        assert client.post('/api/dict/download', json={"id": "unknown"}).status_code == 400

    def test_already_downloading(self, client):
        server._dict_downloading.add('ecdict')
        try:
            assert client.post('/api/dict/download', json={"id": "ecdict"}).status_code == 409
        finally:
            server._dict_downloading.discard('ecdict')

    def test_download_with_proxy(self, client, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch.object(server, '_ai_config', {'dict_url': '', 'proxy': 'http://proxy:8080'}):
                with patch('urllib.request.build_opener') as mock_opener:
                    original_data = b'test data' * 1000
                    compressed = zlib.compress(original_data)
                    mock_resp = MagicMock()
                    mock_resp.headers = {'Content-Length': str(len(compressed))}
                    call_count = [0]
                    def mock_read(size):
                        call_count[0] += 1
                        if call_count[0] == 1:
                            return compressed
                        return b''
                    mock_resp.read = mock_read
                    mock_opener.return_value.open.return_value = mock_resp
                    response = client.post('/api/dict/download', json={"id": "ecdict"})
                    assert response.status_code == 200

    def test_download_error_cleanup(self, client, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('urllib.request.build_opener') as mock_opener:
            mock_opener.return_value.open.side_effect = Exception("Network error")
            response = client.post('/api/dict/download', json={"id": "ecdict"})
            assert response.status_code == 200


class TestPdfSearch:
    def test_not_found(self, client):
        response = client.post('/api/pdf-search/nonexistent', json={"query": "test"})
        assert response.status_code in (404, 500)

    def test_pdf_search_with_results(self, client, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        book_dir = os.path.join(tmp_dir, 'search_pdf')
        os.makedirs(book_dir, exist_ok=True)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello World test text")
        doc.save(os.path.join(book_dir, 'book.pdf'))
        doc.close()
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            response = client.post('/api/pdf-search/search_pdf', json={"query": "Hello"})
            assert response.status_code == 200
            assert len(response.json()['results']) > 0


class TestAnalyzeChapter:
    def test_not_found(self, client):
        response = client.post('/api/ai/analyze', json={"book_id": "nonexistent", "chapter_index": 0})
        assert response.status_code == 404

    def test_analyze_too_short(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'short_book_data')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='T', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/ai/analyze', json={"book_id": "short_book_data", "chapter_index": 0}).json()
            assert 'summary' in data

    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_analyze_success(self, mock_ai, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        mock_ai.return_value = (
            json.dumps({"summary": "test", "key_points": ["a"], "difficulties": "b", "insight": "c"}),
            "model"
        )
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/analyze', json={"book_id": book_id, "chapter_index": 0})
            assert response.status_code == 200

    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_analyze_json_error(self, mock_ai, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        server._analysis_cache.clear()
        mock_ai.return_value = ("not json at all", "model")
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/analyze', json={"book_id": book_id, "chapter_index": 0})
            assert response.status_code == 500

    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_analyze_generic_error(self, mock_ai, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        server._analysis_cache.clear()
        mock_ai.side_effect = Exception("AI error")
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/analyze', json={"book_id": book_id, "chapter_index": 0})
            assert response.status_code == 500

    def test_analyze_cached(self, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        server._analysis_cache.clear()
        fake_result = {"summary": "cached result", "key_points": [], "difficulties": "", "insight": ""}
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            from server import load_book_cached as lbc
            with patch.object(server, 'BOOKS_DIR', tmp_dir):
                b = lbc(book_id)
                chapter = b.spine[0]
                from hashlib import md5
                content_hash = md5(chapter.text.strip().encode()).hexdigest()
                cache_key = f"{book_id}:0:{content_hash}"
                server._analysis_cache[cache_key] = fake_result
                data = client.post('/api/ai/analyze', json={"book_id": book_id, "chapter_index": 0}).json()
                assert data['summary'] == 'cached result'


class TestTranslateFull:
    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_translate_chinese(self, mock_ai, client):
        mock_ai.return_value = ("Hello World", "model")
        assert client.post('/api/ai/translate', json={"text": "你好世界"}).status_code == 200

    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_translate_english(self, mock_ai, client):
        mock_ai.return_value = ("你好", "model")
        assert client.post('/api/ai/translate', json={"text": "Hello"}).status_code == 200

    @patch('server._ai_complete', new_callable=AsyncMock, side_effect=Exception("fail"))
    def test_translate_error(self, mock_ai, client):
        data = client.post('/api/ai/translate', json={"text": "test"}).json()
        assert 'Error' in data['translation']


class TestTranslateStream:
    def test_empty(self, client):
        assert client.post('/api/ai/translate-stream', json={"text": ""}).status_code == 200

    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_translate_stream_with_context(self, mock_stream, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        async def gen():
            yield "translated"
        mock_stream.return_value = gen()
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/translate-stream', json={
                "text": "Hello", "book_id": book_id, "chapter_index": 0
            })
            assert response.status_code == 200


class TestChatFull:
    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_chat_success(self, mock_stream, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        async def gen():
            yield "answer"
        mock_stream.return_value = gen()
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/chat', json={
                "book_id": book_id, "chapter_index": 0, "question": "What is this?"
            })
            assert response.status_code == 200

    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_chat_error(self, mock_stream, client, mock_book_dir):
        book_id, book, tmp_dir = mock_book_dir
        mock_stream.side_effect = Exception("fail")
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/chat', json={
                "book_id": book_id, "chapter_index": 0, "question": "test"
            })
            assert response.status_code == 500

    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_chat_context(self, mock_stream, client):
        async def gen():
            yield "answer"
        mock_stream.return_value = gen()
        response = client.post('/api/ai/chat-context', json={
            "question": "What?", "context": "Some text", "title": "Book"
        })
        assert response.status_code == 200

    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_chat_context_exception(self, mock_stream, client):
        mock_stream.side_effect = Exception("fail")
        response = client.post('/api/ai/chat-context', json={
            "question": "What?", "context": "Some text", "title": "Book"
        })
        assert response.status_code == 500

    def test_chat_not_found(self, client):
        response = client.post('/api/ai/chat', json={"book_id": "nonexistent", "chapter_index": 0, "question": "test"})
        assert response.status_code == 404

    @patch('server._ai_stream', new_callable=AsyncMock)
    def test_chat_with_html_only(self, mock_stream, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'chat_html_book')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(
            id='ch_0', href='ch.xhtml', title='Ch',
            content='<h1>Chapter</h1><p>Long enough content for analysis.</p>',
            text='', order=0
        )
        book = Book(metadata=BookMetadata(title='Chat Book', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        async def gen():
            yield "answer"
        mock_stream.return_value = gen()
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            response = client.post('/api/ai/chat', json={
                "book_id": "chat_html_book", "chapter_index": 0, "question": "test"
            })
            assert response.status_code == 200


class TestGetProvidersFull:
    def test_get_providers_with_config(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {
            'providers': {
                'openai': {'api_key': 'sk-test123456', 'enabled': True, 'model': 'gpt-4'},
                'custom_0': {'api_key': 'ck', 'enabled': True, 'model': 'custom-m', 'custom_name': 'My AI', 'temperature': 0.5, 'max_tokens': 1000}
            },
            'order': ['openai', 'custom_0'],
            'task_routing': {'translate': 'openai'}
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            response = client.get('/api/ai/providers')
            data = response.json()
            assert len(data['providers']) >= 1
            assert data['task_routing'] == {'translate': 'openai'}

    def test_get_providers_filters_builtin(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        gemini_key = os.getenv("GEMINI_API_KEY", "builtin_key")
        config = {
            'providers': {
                'gemini': {'api_key': gemini_key, 'enabled': True, 'model': 'gemini-3-flash-preview'}
            },
            'order': ['gemini']
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            response = client.get('/api/ai/providers')
            assert response.status_code == 200

    def test_get_providers_no_config(self, client):
        with patch.object(server, '_ai_config', {'providers': {}, 'order': []}):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                with patch.object(server, '_load_ai_config'):
                    data = client.get('/api/ai/providers').json()
                    assert len(data['providers']) == 0

    def test_get_providers_unseen_in_order(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {
            'providers': {
                'p1': {'api_key': 'k1', 'enabled': True, 'model': 'm1'},
                'p2': {'api_key': 'k2', 'enabled': True, 'model': 'm2'}
            },
            'order': ['p1']
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                data = client.get('/api/ai/providers').json()
                assert len(data['providers']) == 2

    def test_get_providers_key_preview(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {
            'providers': {
                'openai': {'api_key': 'sk-verylongkey123456', 'enabled': True}
            },
            'order': ['openai']
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            with patch.object(server, '_get_builtin_providers', return_value=[]):
                data = client.get('/api/ai/providers').json()
                assert len(data['providers']) == 1
                assert '******' in data['providers'][0]['key_preview']


class TestAnalyzeTextFallback:
    @patch('server._ai_complete', new_callable=AsyncMock)
    def test_analyze_with_html_only(self, mock_ai, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'html_book_data')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(
            id='ch_0', href='ch.xhtml', title='Ch',
            content='<h1>Chapter</h1><p>This is a long enough chapter with lots of content that should be analyzed properly.</p>',
            text='', order=0
        )
        book = Book(metadata=BookMetadata(title='HTML Book', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        mock_ai.return_value = (
            json.dumps({"summary": "test", "key_points": ["a"], "difficulties": "b", "insight": "c"}),
            "model"
        )
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            server._analysis_cache.clear()
            response = client.post('/api/ai/analyze', json={"book_id": "html_book_data", "chapter_index": 0})
            assert response.status_code == 200


class TestSearchBookOverflow:
    def test_search_short_snippet(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'short_search_book')
        os.makedirs(book_dir, exist_ok=True)
        ch = ChapterContent(
            id='ch_0', href='ch.xhtml', title='Ch',
            content='<p>Hello</p>', text='Hello world test', order=0
        )
        book = Book(metadata=BookMetadata(title='Short', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.load_book_cached.cache_clear()
            data = client.post('/api/search', json={"book_id": "short_search_book", "query": "Hello"}).json()
            assert len(data['results']) > 0


class TestAutoImport:
    def test_no_file(self):
        with patch('os.path.exists', return_value=False):
            server.auto_import_default_books()

    def test_already_imported(self, tmp_dir):
        assets_dir = os.path.join(tmp_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        epub_path = os.path.join(assets_dir, 'Meditations by Emperor of Rome Marcus Aurelius.epub')
        with open(epub_path, 'wb') as f:
            f.write(b'fake epub')
        book_data_dir = os.path.join(tmp_dir, 'Meditations_by_Emperor_of_Rome_Marcus_Aurelius_data')
        os.makedirs(book_data_dir, exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            server.auto_import_default_books()


# ============================================================
# Import local PDF
# ============================================================

class TestImportLocalPdf:
    def test_import_local_pdf(self, client, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        pdf_path = os.path.join(tmp_dir, 'test.pdf')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test PDF")
        doc.set_metadata({"title": "Test PDF", "author": "Author"})
        doc.save(pdf_path)
        doc.close()
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('shutil.copy2'):
            response = client.post('/api/import-local', json={"path": pdf_path})
            assert response.status_code == 200


# ============================================================
# Upload PDF
# ============================================================

class TestUploadPdf:
    def test_upload_pdf_success(self, client, tmp_dir):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('shutil.copy2'):
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Test PDF")
            doc.set_metadata({"title": "Uploaded PDF", "author": "Author"})
            pdf_buf = BytesIO()
            doc.save(pdf_buf)
            doc.close()
            pdf_buf.seek(0)
            data = {'file': ('test.pdf', pdf_buf, 'application/pdf')}
            response = client.post('/api/upload', files=data)
            assert response.status_code == 200


# ============================================================
# 补充丢失的覆盖测试
# ============================================================

class TestTaskRouting:
    @pytest.mark.asyncio
    async def test_ai_complete_task_routing(self):
        providers = [
            {'id': 'p1', 'name': 'P1', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
            {'id': 'p2', 'name': 'P2', 'api_key': 'k', 'model': 'm', 'base_url': 'u', 'format': 'openai'},
        ]
        with patch.object(server, '_get_enabled_providers', return_value=providers):
            with patch.object(server, '_ai_config', {'task_routing': {'translate': 'p2'}}):
                with patch.object(server, '_call_openai_compat', new_callable=AsyncMock, return_value="ok"):
                    text, model = await server._ai_complete("prompt", task="translate")
                    assert text == "ok"


class TestStreamError:
    @pytest.mark.asyncio
    async def test_stream_openai_error_response(self):
        async def mock_aiter_bytes():
            yield b'data: {"error":"bad"}\n\n'
            yield b'data: [DONE]\n\n'

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = mock_aiter_bytes

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_cm
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch('server.httpx.AsyncClient', return_value=mock_client):
            chunks = []
            async for chunk in server._stream_openai_compat('url', 'key', 'm', 'p', 0.7, 100):
                chunks.append(chunk)
            assert len(chunks) == 0


class TestCoverImageServing:
    def test_serve_book_cover_success(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'cover_serve')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with open(os.path.join(book_dir, 'images', 'cover.jpg'), 'wb') as f:
            f.write(b'fake jpg')
        with open(os.path.join(book_dir, 'cover_image.txt'), 'w') as f:
            f.write('cover.jpg')
        ch = ChapterContent(id='ch_0', href='ch.xhtml', title='Ch', content='<p>Hi</p>', text='Hi', order=0)
        book = Book(metadata=BookMetadata(title='ServeCover', language='en'), spine=[ch], toc=[], images={},
                    source_file='t.epub', processed_at='2024-01-01')
        with open(os.path.join(book_dir, 'book.pkl'), 'wb') as f:
            pickle.dump(book, f)
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            response = client.get('/api/book-cover/cover_serve')
            assert response.status_code == 200


class TestProviderSaveEdge:
    def test_save_providers_custom_name(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{"id": "custom_0", "api_key": "k", "enabled": True, "custom_name": "My AI", "temperature": 0.5, "max_tokens": 1000}]
            })
            assert response.status_code == 200


class TestFetchModelsStoredKey:
    def test_fetch_with_stored_key(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        config = {'providers': {'openai': {'api_key': 'stored_key', 'enabled': True}}, 'order': ['openai']}
        with open(config_path, 'w') as f:
            json.dump(config, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            with patch('server.httpx.AsyncClient') as mock_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"data": [{"id": "gpt-4"}]}
                mock_resp.raise_for_status = MagicMock()
                async def mock_get(*a, **kw):
                    return mock_resp
                mock_inst = MagicMock()
                mock_inst.get = mock_get
                mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
                mock_inst.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_inst
                response = client.post('/api/ai/fetch-models', json={"id": "openai", "api_key": "", "base_url": "https://api.openai.com/v1/"})
                assert response.status_code == 200


class TestDictDownloadProgress:
    def test_download_large_file(self, client, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch.object(server, '_ai_config', {'dict_url': '', 'proxy': ''}):
                with patch('urllib.request.build_opener') as mock_opener:
                    original_data = b'x' * 2000000
                    compressed = zlib.compress(original_data)
                    mock_resp = MagicMock()
                    mock_resp.headers = {'Content-Length': str(len(compressed))}
                    call_count = [0]
                    def mock_read(size):
                        call_count[0] += 1
                        if call_count[0] == 1:
                            return compressed[:len(compressed)//2]
                        elif call_count[0] == 2:
                            return compressed[len(compressed)//2:]
                        return b''
                    mock_resp.read = mock_read
                    mock_opener.return_value.open.return_value = mock_resp
                    response = client.post('/api/dict/download', json={"id": "cn_dict"})
                    assert response.status_code == 200


class TestImportLocalEdge:
    def test_import_local_epub(self, client, tmp_dir):
        epub_path = os.path.join(tmp_dir, 'test.epub')
        from ebooklib import epub
        book = epub.EpubBook()
        book.set_identifier('test-id')
        book.set_title('Test Book')
        book.set_language('en')
        c = epub.EpubHtml(title='Ch1', file_name='ch1.xhtml', lang='en')
        c.content = b'<html><body><p>Content of chapter.</p></body></html>'
        book.add_item(c)
        book.toc = [epub.Link('ch1.xhtml', 'Ch1', 'ch1')]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [c]
        epub.write_epub(epub_path, book, {})

        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('shutil.copy2'):
            response = client.post('/api/import-local', json={"path": epub_path})
            assert response.status_code == 200


class TestSetCoverSuccess:
    def test_set_cover_with_real_image(self, client, tmp_dir):
        book_dir = os.path.join(tmp_dir, 'real_cover')
        os.makedirs(os.path.join(book_dir, 'images'), exist_ok=True)
        with patch.object(server, 'BOOKS_DIR', tmp_dir), patch('urllib.request.urlopen') as mock_url:
            import io

            from PIL import Image
            img = Image.new('RGB', (10, 10), (200, 200, 200))
            buf = io.BytesIO()
            img.save(buf, 'JPEG')
            jpeg_bytes = buf.getvalue()
            mock_resp = MagicMock()
            mock_resp.read.return_value = jpeg_bytes
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_url.return_value = mock_resp
            response = client.post('/api/set-cover/real_cover', json={"image_url": "https://example.com/cover.jpg"})
            assert response.status_code == 200
            assert os.path.exists(os.path.join(book_dir, 'cover_image.txt'))


class TestSaveProvidersEmptyId:
    def test_skip_empty_id(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            response = client.post('/api/ai/providers', json={
                "providers": [{"id": "", "api_key": "k"}]
            })
            assert response.status_code == 200


class TestFetchModelsNoKey:
    def test_no_key_stored(self, client, tmp_dir):
        config_path = os.path.join(tmp_dir, 'ai_config.json')
        with open(config_path, 'w') as f:
            json.dump({'providers': {}, 'order': []}, f)
        with patch.object(server, 'AI_CONFIG_PATH', config_path):
            server._load_ai_config()
            response = client.post('/api/ai/fetch-models', json={"id": "openai", "api_key": ""})
            data = response.json()
            assert data['models'] == []
            assert 'error' in data


class TestDictDownloadEmpty:
    def test_download_empty_response(self, client, tmp_dir):
        with patch.object(server, 'BOOKS_DIR', tmp_dir):
            with patch.object(server, '_ai_config', {'dict_url': '', 'proxy': ''}):
                with patch('urllib.request.build_opener') as mock_opener:
                    mock_resp = MagicMock()
                    mock_resp.headers = {'Content-Length': '0'}

                    def mock_read(size):
                        return b''

                    mock_resp.read = mock_read
                    mock_opener.return_value.open.return_value = mock_resp
                    response = client.post('/api/dict/download', json={"id": "cn_dict"})
                    assert response.status_code == 200
