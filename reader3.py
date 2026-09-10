"""
Parses an EPUB file into a structured object that can be used to serve the book via a web interface.
"""

import os
import pickle
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup, Comment
from ebooklib import epub

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


def parse_toc_recursive(toc_list, depth=0) -> list[TOCEntry]:
    """
    Recursively parses the TOC structure from ebooklib.
    """
    result = []

    for item in toc_list:
        try:
            # ebooklib TOC items are either `Link` objects or tuples (Section, [Children])
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
            elif isinstance(item, epub.Link):
                href = item.href or ""
                entry = TOCEntry(
                    title=item.title or "Untitled",
                    href=href,
                    file_href=href.split('#')[0] if href else "",
                    anchor=href.split('#')[1] if href and '#' in href else ""
                )
                result.append(entry)
            elif isinstance(item, epub.Section):
                 href = ""
                 if hasattr(item, 'href') and item.href:
                     h = item.href
                     if isinstance(h, list) and h:
                         first = h[0]
                         if isinstance(first, epub.Link):
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


def get_fallback_toc(book_obj) -> list[TOCEntry]:
    """
    If TOC is missing, build a flat one from all documents.
    """
    toc = []
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            name = item.get_name()
            title = name.replace('.html', '').replace('.xhtml', '').replace('_', ' ').title()
            toc.append(TOCEntry(title=title, href=name, file_href=name, anchor=""))
    return toc


def extract_metadata_robust(book_obj) -> BookMetadata:
    """
    Extracts metadata handling both single and list values.
    """
    def get_list(key):
        data = book_obj.get_metadata('DC', key)
        return [str(x[0]) for x in data] if data else []

    def get_one(key):
        data = book_obj.get_metadata('DC', key)
        return str(data[0][0]) if data else None

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


# --- Main Conversion Logic ---

def process_epub(epub_path: str, output_dir: str) -> Book:

    # 1. Load Book
    print(f"Loading {epub_path}...")
    book = epub.read_epub(epub_path)

    # 2. Extract Metadata
    metadata = extract_metadata_robust(book)

    # 3. Prepare Output Directories
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    # 4. Extract Images & Build Map
    print("Extracting images...")
    image_map = {} # Key: internal_path, Value: local_relative_path

    for item in book.get_items():
        if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
            # Normalize filename
            original_fname = os.path.basename(item.get_name())
            # Sanitize filename for OS
            safe_fname = "".join([c for c in original_fname if c.isalpha() or c.isdigit() or c in '._-']).strip()

            # Save to disk
            local_path = os.path.join(images_dir, safe_fname)
            try:
                with open(local_path, 'wb') as f:
                    f.write(item.get_content())
                # Map keys: We try both the full internal path and just the basename
                # to be robust against messy HTML src attributes
                rel_path = f"images/{safe_fname}"
                image_map[item.get_name()] = rel_path
                image_map[original_fname] = rel_path
            except Exception as e:
                print(f"Warning: Failed to extract image {original_fname}: {e}")

    # 4b. Extract cover image from epub metadata and write marker file
    cover_fname = None
    try:
        # Method A: OPF <meta name="cover" content="item-id">
        cover_id = None
        for meta in book.get_metadata('OPF', 'cover') or []:
            if meta and meta[1] and 'content' in meta[1]:
                cover_id = meta[1]['content']
                break
        if cover_id:
            item = book.get_item_with_id(cover_id)
            if item:
                fname = os.path.basename(item.get_name())
                cover_fname = "".join([c for c in fname if c.isalpha() or c.isdigit() or c in '._-']).strip()
        # Method B: item with properties="cover-image" (EPUB3)
        if not cover_fname:
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_COVER:
                    fname = os.path.basename(item.get_name())
                    cover_fname = "".join([c for c in fname if c.isalpha() or c.isdigit() or c in '._-']).strip()
                    break
    except Exception:
        pass
    if cover_fname and os.path.exists(os.path.join(images_dir, cover_fname)):
        with open(os.path.join(output_dir, "cover_image.txt"), "w") as f:
            f.write(cover_fname)
        print(f"Cover image: {cover_fname}")

    # 5. Process TOC
    print("Parsing Table of Contents...")
    toc_structure = parse_toc_recursive(book.toc)
    if not toc_structure:
        print("Warning: Empty TOC, building fallback from content...")
        toc_structure = get_fallback_toc(book)

    # 6. Process Content (Collect all Document Items)
    print("Processing chapters...")

    # Aggressive document collection: Any file ending in .html or .xhtml
    # This is more robust than relying on the EPUB's internal type metadata
    all_docs = {
        item.get_name(): item
        for item in book.get_items()
        if item.get_name().lower().endswith(('.html', '.xhtml', '.htm'))
    }

    spine_names = []
    for spine_item in book.spine:
        item_id = spine_item[0]
        item = book.get_item_with_id(item_id)
        if item and item.get_name().lower().endswith(('.html', '.xhtml', '.htm')):
            spine_names.append(item.get_name())

    # Add any document that isn't in the spine
    all_names = list(all_docs.keys())
    # Sort them to keep some semblance of order for non-spine items
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
        item_id = item.get_id()

        try:
            # Raw content
            content_bytes = item.get_content()
            raw_content = content_bytes.decode('utf-8', errors='ignore')

            # Skip very short or empty documents (often placeholders)
            if len(raw_content) < 50 and i > 0: # keep first one if it's a cover
                continue

            soup = BeautifulSoup(raw_content, 'html.parser')

            # A. Fix Images
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if not src: continue
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
