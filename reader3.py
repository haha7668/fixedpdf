"""
Parses an EPUB file into a structured object that can be used to serve the book via a web interface.

EPUB 解析基于 Python 标准库（zipfile + xml.etree.ElementTree）。EPUB 本质是一个 ZIP 容器，
内含 OPF 清单（manifest/spine/metadata）、章节 XHTML 内容，以及 NCX（EPUB2）或 nav.xhtml
（EPUB3）导航目录。本模块不再依赖 EbookLib（AGPL-3.0）。
"""

import os
import pickle
import posixpath
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote

from bs4 import BeautifulSoup, Comment, NavigableString

# --- XML 命名空间 ---
NS_CONTAINER = '{urn:oasis:names:tc:opendocument:xmlns:container}'
NS_OPF = '{http://www.idpf.org/2007/opf}'
NS_DC = '{http://purl.org/dc/elements/1.1/}'
NS_NCX = '{http://www.daisy.org/z3986/2005/ncx/}'


# --- Data structures ---

@dataclass
class ChapterContent:
    """
    Represents a physical file in the EPUB (Spine Item).
    A single file might contain multiple logical chapters (TOC entries).
    """
    id: str           # Internal ID (e.g., 'item_1')
    href: str         # Filename (e.g., 'part01.html')
    title: str        # Best guess title from file
    content: str      # Cleaned HTML with rewritten image paths
    text: str         # Plain text for search/LLM context
    order: int        # Linear reading order


@dataclass
class TOCEntry:
    """Represents a logical entry in the navigation sidebar."""
    title: str
    href: str         # original href (e.g., 'part01.html#chapter1')
    file_href: str    # just the filename (e.g., 'part01.html')
    anchor: str       # just the anchor (e.g., 'chapter1'), empty if none
    children: list['TOCEntry'] = field(default_factory=list)


@dataclass
class Link:
    """TOC 叶子节点：带超链接的章节条目（替代 ebooklib 的 Link）。"""
    href: str = ""
    title: str = ""
    uid: str = ""


@dataclass
class Section:
    """TOC 容器节点：带子节点的分节标题，可无 href（替代 ebooklib 的 Section）。"""
    title: str = ""
    href: object = None


@dataclass
class BookMetadata:
    """Metadata"""
    title: str
    language: str
    authors: list[str] = field(default_factory=list)
    description: str | None = None
    publisher: str | None = None
    date: str | None = None
    identifiers: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)


@dataclass
class Book:
    """The Master Object to be pickled."""
    metadata: BookMetadata
    spine: list[ChapterContent]  # The actual content (linear files)
    toc: list[TOCEntry]          # The navigation tree
    images: dict[str, str]       # Map: original_path -> local_path

    # Meta info
    source_file: str
    processed_at: str
    version: str = "3.0"


# --- 内部：EPUB 包结构 ---

@dataclass
class _ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str = ""


@dataclass
class _EpubPackage:
    metadata: dict = field(default_factory=dict)  # dc 字段 -> list[str]
    manifest: dict = field(default_factory=dict)  # id -> _ManifestItem
    spine: list = field(default_factory=list)     # list of idref (阅读顺序)
    toc: list = field(default_factory=list)       # list of Link / Section / tuples
    cover_id: str | None = None                   # OPF <meta name="cover" content="...">
    opf_dir: str = ""                             # OPF 文件所在目录（用于解析 href）


# --- Utilities ---

def clean_html_content(soup: BeautifulSoup) -> BeautifulSoup:

    # Remove dangerous/useless tags
    for tag in soup(['script', 'style', 'iframe', 'video', 'nav', 'form', 'button']):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove input tags
    for tag in soup.find_all('input'):
        tag.decompose()

    return soup


def extract_plain_text(soup: BeautifulSoup) -> str:
    """Extract clean text for LLM/Search usage."""
    text = soup.get_text(separator=' ')
    # Collapse whitespace
    return ' '.join(text.split())


def _sanitize_filename(name: str) -> str:
    """保留字母、数字及 . _ -，去除路径分隔符与其它字符。"""
    return "".join([c for c in name if c.isalpha() or c.isdigit() or c in '._-']).strip()


def parse_toc_recursive(toc_list, depth=0) -> list[TOCEntry]:
    """
    Recursively parses the TOC structure.

    toc_list 的元素可以是：Link、Section，或 (Section, [children]) 元组。
    """
    result = []

    for item in toc_list:
        try:
            # TOC 元素可能是 Link 对象，或 (Section, [Children]) 元组
            if isinstance(item, tuple):
                section, children = item
                child_entries = parse_toc_recursive(children, depth + 1)

                # Some magazines have sections without an href (just a label)
                href = getattr(section, 'href', "") or ""
                if not href and child_entries:
                    # Use the first child's href as a fallback for the parent container
                    href = child_entries[0].href

                entry = TOCEntry(
                    title=getattr(section, 'title', "Untitled Section"),
                    href=href,
                    file_href=href.split('#')[0] if href else "",
                    anchor=href.split('#')[1] if href and '#' in href else "",
                    children=child_entries
                )
                result.append(entry)
            elif isinstance(item, Link):
                href = item.href or ""
                entry = TOCEntry(
                    title=item.title or "Untitled",
                    href=href,
                    file_href=href.split('#')[0] if href else "",
                    anchor=href.split('#')[1] if href and '#' in href else ""
                )
                result.append(entry)
            elif isinstance(item, Section):
                href = ""
                if hasattr(item, 'href') and item.href:
                    h = item.href
                    if isinstance(h, list) and h:
                        first = h[0]
                        if isinstance(first, Link):
                            href = first.href
                        else:
                            href = str(first)
                    elif isinstance(h, str):
                        href = h
                entry = TOCEntry(
                    title=item.title or "Untitled",
                    href=href,
                    file_href=href.split('#')[0] if href else "",
                    anchor=href.split('#')[1] if href and '#' in href else ""
                )
                result.append(entry)
        except Exception as e:
            print(f"Warning: Skipping TOC item due to error: {e}")

    return result


def get_fallback_toc(items) -> list[TOCEntry]:
    """
    If TOC is missing, build a flat one from all document items.

    items: 可迭代对象，每个元素需有 href 与 media_type 属性（如 _ManifestItem）。
    """
    toc = []
    for item in items:
        href = getattr(item, 'href', '') or ''
        media_type = getattr(item, 'media_type', '') or ''
        is_document = ('html' in media_type.lower()) or href.lower().endswith(('.html', '.xhtml', '.htm'))
        if not is_document:
            continue
        title = href.replace('.html', '').replace('.xhtml', '').replace('_', ' ').title()
        toc.append(TOCEntry(title=title, href=href, file_href=href, anchor=""))
    return toc


def extract_metadata_robust(metadata: dict) -> BookMetadata:
    """
    Extracts metadata from a mapping of DC field -> list of values.

    metadata 的键为小写 DC 字段名：title / language / creator / description /
    publisher / date / identifier / subject。
    """
    def get_list(key):
        data = metadata.get(key, [])
        return [str(x) for x in data] if data else []

    def get_one(key):
        data = metadata.get(key, [])
        return str(data[0]) if data else None

    return BookMetadata(
        title=get_one('title') or "Untitled",
        language=get_one('language') or "en",
        authors=get_list('creator'),
        description=get_one('description'),
        publisher=get_one('publisher'),
        date=get_one('date'),
        identifiers=get_list('identifier'),
        subjects=get_list('subject')
    )


# --- EPUB 解析（标准库实现）---

def _find_opf_path(zf: zipfile.ZipFile) -> str | None:
    """从 container.xml 定位 OPF 文件路径，失败则扫描 .opf 文件。"""
    try:
        data = zf.read('META-INF/container.xml')
    except KeyError:
        data = None
    if data is not None:
        try:
            root = ET.fromstring(data)
            rootfiles = root.find(NS_CONTAINER + 'rootfiles')
            if rootfiles is not None:
                for rf in rootfiles.findall(NS_CONTAINER + 'rootfile'):
                    full = rf.get('full-path')
                    if full:
                        return posixpath.normpath(full)
        except ET.ParseError:
            pass
    # 兜底：查找任意 .opf 文件
    for name in zf.namelist():
        if name.lower().endswith('.opf'):
            return name
    return None


def _read_href(zf: zipfile.ZipFile, opf_dir: str, href: str) -> bytes | None:
    """按 OPF 目录解析 href，从 zip 读取内容；支持 URL 编码与裸路径兜底。"""
    candidates = []
    raw = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else posixpath.normpath(href)
    candidates.append(raw)
    decoded = unquote(raw)
    if decoded != raw:
        candidates.append(decoded)
    bare = posixpath.normpath(href)
    if bare not in candidates:
        candidates.append(bare)
    for candidate in candidates:
        try:
            return zf.read(candidate)
        except KeyError:
            continue
    return None


def _parse_nav_toc(zf: zipfile.ZipFile, opf_dir: str, nav_href: str) -> list:
    """EPUB3：解析 nav.xhtml 里的 <nav epub:type="toc">。"""
    data = _read_href(zf, opf_dir, nav_href)
    if data is None:
        return []
    soup = BeautifulSoup(data.decode('utf-8', errors='ignore'), 'html.parser')
    nav = soup.find('nav', attrs={'epub:type': 'toc'})
    if nav is None:
        nav = soup.find('nav')
    if nav is None:
        return []
    ol = nav.find('ol')
    if ol is None:
        return []
    return _walk_nav_ol(ol)


def _walk_nav_ol(ol) -> list:
    result = []
    for li in ol.find_all('li', recursive=False):
        a = li.find('a', recursive=False)
        sub_ol = li.find('ol', recursive=False)
        if a is not None:
            node = Link(href=a.get('href', '') or '', title=a.get_text(strip=True))
        else:
            span = li.find('span', recursive=False)
            if span is not None:
                title = span.get_text(strip=True)
            else:
                title = ''.join(str(c) for c in li.contents if isinstance(c, NavigableString)).strip()
            node = Section(title=title)
        if sub_ol is not None:
            result.append((node, _walk_nav_ol(sub_ol)))
        else:
            result.append(node)
    return result


def _parse_ncx_toc(zf: zipfile.ZipFile, opf_dir: str, ncx_href: str) -> list:
    """EPUB2：解析 toc.ncx 的 navMap。"""
    data = _read_href(zf, opf_dir, ncx_href)
    if data is None:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    navmap = root.find(NS_NCX + 'navMap')
    if navmap is None:
        navmap = root
    return _walk_ncx(navmap)


def _walk_ncx(parent) -> list:
    result = []
    for np in parent.findall(NS_NCX + 'navPoint'):
        label = np.find(NS_NCX + 'navLabel/' + NS_NCX + 'text')
        title = (label.text or '').strip() if label is not None and label.text else 'Untitled'
        content = np.find(NS_NCX + 'content')
        href = content.get('src', '') if content is not None else ''
        children = _walk_ncx(np)
        if children:
            result.append((Section(title=title, href=href), children))
        else:
            result.append(Link(href=href, title=title))
    return result


def _parse_package(zf: zipfile.ZipFile) -> _EpubPackage:
    """解析 OPF 清单，返回内部包结构（不含内容字节）。"""
    opf_path = _find_opf_path(zf)
    if opf_path is None:
        raise ValueError("EPUB 缺少 container.xml 或 OPF 文件")
    opf_dir = posixpath.dirname(opf_path)
    opf = ET.fromstring(zf.read(opf_path))

    package = _EpubPackage()

    # metadata
    metadata_el = opf.find(NS_OPF + 'metadata')
    if metadata_el is not None:
        for child in metadata_el:
            if child.tag.startswith(NS_DC):
                key = child.tag[len(NS_DC):]
                value = (child.text or '').strip()
                package.metadata.setdefault(key, []).append(value)
        for meta in metadata_el.findall(NS_OPF + 'meta'):
            if meta.get('name') == 'cover':
                package.cover_id = meta.get('content')
                break

    # manifest
    manifest_el = opf.find(NS_OPF + 'manifest')
    if manifest_el is not None:
        for item in manifest_el.findall(NS_OPF + 'item'):
            iid = item.get('id')
            href = item.get('href')
            if not iid or not href:
                continue
            package.manifest[iid] = _ManifestItem(
                id=iid,
                href=href,
                media_type=item.get('media-type') or '',
                properties=item.get('properties') or '',
            )

    # spine
    spine_el = opf.find(NS_OPF + 'spine')
    ncx_id = None
    if spine_el is not None:
        for itemref in spine_el.findall(NS_OPF + 'itemref'):
            idref = itemref.get('idref')
            if idref:
                package.spine.append(idref)
        ncx_id = spine_el.get('toc')  # EPUB2：spine 的 toc 属性指向 NCX manifest id

    # TOC：优先 EPUB3 nav，其次 EPUB2 NCX
    nav_item = None
    for item in package.manifest.values():
        if 'nav' in (item.properties or ''):
            nav_item = item
            break
    ncx_item = None
    if ncx_id and ncx_id in package.manifest:
        ncx_item = package.manifest[ncx_id]
    if ncx_item is None:
        for item in package.manifest.values():
            if item.media_type == 'application/x-dtbncx+xml':
                ncx_item = item
                break

    if nav_item is not None:
        package.toc = _parse_nav_toc(zf, opf_dir, nav_item.href)
    if not package.toc and ncx_item is not None:
        package.toc = _parse_ncx_toc(zf, opf_dir, ncx_item.href)

    package.opf_dir = opf_dir
    return package


# --- Main Conversion Logic ---

def process_epub(epub_path: str, output_dir: str) -> Book:

    # 1. Load Package
    print(f"Loading {epub_path}...")
    with zipfile.ZipFile(epub_path) as zf:
        package = _parse_package(zf)
        opf_dir = package.opf_dir

        # 2. Extract Metadata
        metadata = extract_metadata_robust(package.metadata)

        # 3. Prepare Output Directories
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        images_dir = os.path.join(output_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)

        # 4. Extract Images & Build Map
        print("Extracting images...")
        image_map = {}  # Key: internal_path, Value: local_relative_path

        for item in package.manifest.values():
            if not (item.media_type or '').startswith('image/'):
                continue
            original_fname = os.path.basename(item.href)
            safe_fname = _sanitize_filename(original_fname)

            local_path = os.path.join(images_dir, safe_fname)
            try:
                content = _read_href(zf, opf_dir, item.href)
                if content is None:
                    raise FileNotFoundError(item.href)
                with open(local_path, 'wb') as f:
                    f.write(content)
                # Map keys: full internal path 与 basename 都映射，兼容 messy HTML src
                rel_path = f"images/{safe_fname}"
                image_map[item.href] = rel_path
                image_map[original_fname] = rel_path
            except Exception as e:
                print(f"Warning: Failed to extract image {original_fname}: {e}")

        # 4b. Extract cover image and write marker file
        cover_fname = None
        try:
            # Method A: OPF <meta name="cover" content="item-id">
            cover_id = package.cover_id
            if cover_id:
                item = package.manifest.get(cover_id)
                if item:
                    cover_fname = _sanitize_filename(os.path.basename(item.href))
            # Method B: item with properties="cover-image" (EPUB3)
            if not cover_fname:
                for item in package.manifest.values():
                    if 'cover-image' in (item.properties or ''):
                        cover_fname = _sanitize_filename(os.path.basename(item.href))
                        break
        except Exception:
            pass
        if cover_fname and os.path.exists(os.path.join(images_dir, cover_fname)):
            with open(os.path.join(output_dir, "cover_image.txt"), "w") as f:
                f.write(cover_fname)
            print(f"Cover image: {cover_fname}")

        # 5. Process TOC
        print("Parsing Table of Contents...")
        toc_structure = parse_toc_recursive(package.toc)
        if not toc_structure:
            print("Warning: Empty TOC, building fallback from content...")
            toc_structure = get_fallback_toc(package.manifest.values())

        # 6. Process Content (Collect all Document Items)
        print("Processing chapters...")

        all_docs = {
            item.href: item
            for item in package.manifest.values()
            if item.href.lower().endswith(('.html', '.xhtml', '.htm'))
        }

        spine_names = []
        for item_id in package.spine:
            item = package.manifest.get(item_id)
            if item and item.href.lower().endswith(('.html', '.xhtml', '.htm')):
                spine_names.append(item.href)

        # Add any document that isn't in the spine
        all_names = list(all_docs.keys())
        all_names.sort()

        final_names_ordered = []
        seen = set()

        # 1. Spine first
        for name in spine_names:
            if name not in seen:
                final_names_ordered.append(name)
                seen.add(name)

        # 2. Everything else
        for name in all_names:
            # Skip common non-content items if they aren't in spine
            if name.lower() in ('nav.xhtml', 'toc.xhtml', 'navigation.xhtml'):
                continue
            if name not in seen:
                final_names_ordered.append(name)
                seen.add(name)

        spine_chapters = []
        order_counter = 0
        for i, name in enumerate(final_names_ordered):
            item = all_docs[name]
            item_id = item.id

            try:
                content_bytes = _read_href(zf, opf_dir, name)
                if content_bytes is None:
                    print(f"Error processing chapter {name}: content not found")
                    continue
                raw_content = content_bytes.decode('utf-8', errors='ignore')

                # Skip very short or empty documents (often placeholders)
                if len(raw_content) < 50 and i > 0:  # keep first one if it's a cover
                    continue

                soup = BeautifulSoup(raw_content, 'html.parser')

                # A. Fix Images
                for img in soup.find_all('img'):
                    src = img.get('src', '')
                    if not src:
                        continue
                    src_decoded = unquote(src)
                    filename = os.path.basename(src_decoded)
                    if src_decoded in image_map:
                        img['src'] = image_map[src_decoded]
                    elif filename in image_map:
                        img['src'] = image_map[filename]

                # B. Clean HTML
                soup = clean_html_content(soup)

                # C. Extract Body Content only
                body = soup.find('body')
                if body:
                    final_html = "".join([str(x) for x in body.contents])
                else:
                    final_html = str(soup)

                # D. Create Object
                chapter = ChapterContent(
                    id=item_id,
                    href=name,
                    title=f"Section {order_counter + 1}",
                    content=final_html,
                    text=extract_plain_text(soup),
                    order=order_counter
                )
                spine_chapters.append(chapter)
                order_counter += 1
            except Exception as e:
                print(f"Error processing chapter {name}: {e}")

    # 7. Final Assembly
    final_book = Book(
        metadata=metadata,
        spine=spine_chapters,
        toc=toc_structure,
        images=image_map,
        source_file=os.path.basename(epub_path),
        processed_at=datetime.now().isoformat()
    )

    return final_book


def save_to_pickle(book: Book, output_dir: str):
    p_path = os.path.join(output_dir, 'book.pkl')
    with open(p_path, 'wb') as f:
        pickle.dump(book, f)
    print(f"Saved structured data to {p_path}")


# --- CLI ---

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 2:
        print("Usage: python reader3.py <file.epub>")
        sys.exit(1)

    epub_file = sys.argv[1]
    assert os.path.exists(epub_file), "File not found."
    out_dir = os.path.splitext(epub_file)[0] + "_data"

    book_obj = process_epub(epub_file, out_dir)
    save_to_pickle(book_obj, out_dir)
    print("\n--- Summary ---")
    print(f"Title: {book_obj.metadata.title}")
    print(f"Authors: {', '.join(book_obj.metadata.authors)}")
    print(f"Physical Files (Spine): {len(book_obj.spine)}")
    print(f"TOC Root Items: {len(book_obj.toc)}")
    print(f"Images extracted: {len(book_obj.images)}")
