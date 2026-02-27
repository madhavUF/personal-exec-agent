"""
Document Loader
================

Drop your files in the 'my_data' folder and run this script.
It will load them into documents.json automatically.

Supports:
- .txt files
- .md files (markdown)
- .pdf files (extracts text)
- .docx files (Word documents)
- .json files (if structured as {title, content})
- .jpg, .jpeg, .png files (OCR via docTR)

Usage:
1. Create folder: my_data/
2. Add your files there
3. Run: python load_documents.py
4. Run: python rag.py (to search and query)
"""

import os
import json
from datetime import datetime
from pathlib import Path

# PDF support
try:
    from pypdf import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("Note: Install 'pypdf' for PDF support: pip install pypdf")

# Word doc support
try:
    from docx import Document as DocxDocument
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False
    print("Note: Install 'python-docx' for Word doc support: pip install python-docx")

# PyMuPDF for rendering PDF pages to images (needed for OCR)
try:
    import fitz  # PyMuPDF
    FITZ_SUPPORT = True
except ImportError:
    FITZ_SUPPORT = False

# OCR support (docTR - lazy loaded)
OCR_SUPPORT = False
_ocr_predictor = None

def _get_ocr_predictor():
    """Lazy-load docTR OCR model (only when first needed)."""
    global OCR_SUPPORT, _ocr_predictor
    if _ocr_predictor is not None:
        return _ocr_predictor
    try:
        from doctr.models import ocr_predictor
        print("    → Loading docTR OCR model...")
        _ocr_predictor = ocr_predictor(pretrained=True)
        OCR_SUPPORT = True
        return _ocr_predictor
    except ImportError:
        print("Note: Install 'python-doctr[torch]' for OCR support")
        return None
    except Exception as e:
        print(f"    → docTR load error: {e}")
        return None

# =============================================================================
# Configuration
# =============================================================================

_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.path.join(_BASE, 'my_data')
OUTPUT_FILE = os.path.join(_BASE, 'data', 'documents.json')
MIN_TEXT_THRESHOLD = 100  # chars below which we try OCR

# =============================================================================
# Create data folder if it doesn't exist
# =============================================================================

os.makedirs(DATA_FOLDER, exist_ok=True)
print(f"Data folder: {DATA_FOLDER}")
print()

# =============================================================================
# Load functions for different file types
# =============================================================================

def load_txt(filepath):
    """Load a .txt file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    title = Path(filepath).stem.replace('_', ' ').replace('-', ' ').title()

    return {
        'title': title,
        'content': content.strip()
    }

def load_md(filepath):
    """Load a .md markdown file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    title = Path(filepath).stem.replace('_', ' ').replace('-', ' ').title()

    for line in lines:
        if line.startswith('# '):
            title = line[2:].strip()
            break

    return {
        'title': title,
        'content': content.strip()
    }

def load_json_doc(filepath):
    """Load a .json file (expects {title, content} or just text)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        return {
            'title': data.get('title', Path(filepath).stem),
            'content': data.get('content', str(data))
        }
    else:
        return {
            'title': Path(filepath).stem,
            'content': str(data)
        }

def load_pdf(filepath):
    """Load a .pdf file - extracts text, uses OCR if needed."""
    if not PDF_SUPPORT:
        raise ImportError("pypdf not installed")

    # First try normal text extraction
    reader = PdfReader(filepath)
    text_parts = []

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)

    content = '\n\n'.join(text_parts)
    title = Path(filepath).stem.replace('_', ' ').replace('-', ' ').title()

    # If we got very little text, try OCR
    if len(content.strip()) < MIN_TEXT_THRESHOLD:
        print(f"    → Low text ({len(content.strip())} chars), trying OCR for {Path(filepath).name}...")
        ocr_text = ocr_pdf(filepath)
        if ocr_text and len(ocr_text.strip()) > len(content.strip()):
            content = ocr_text

    return {
        'title': title,
        'content': content.strip(),
        'pages': len(reader.pages)
    }


def ocr_pdf(filepath):
    """Extract text from PDF using docTR OCR."""
    predictor = _get_ocr_predictor()
    if predictor is None:
        return ""

    try:
        from doctr.io import DocumentFile

        doc = DocumentFile.from_pdf(filepath)
        result = predictor(doc)

        text_parts = []
        for page in result.pages:
            page_text = []
            for block in page.blocks:
                for line in block.lines:
                    line_text = ' '.join(word.value for word in line.words)
                    page_text.append(line_text)
            text_parts.append('\n'.join(page_text))

        return '\n\n'.join(text_parts)

    except Exception as e:
        print(f"    → OCR error: {e}")
        return ""


def load_image(filepath):
    """Load an image file and extract text via docTR OCR."""
    predictor = _get_ocr_predictor()
    if predictor is None:
        return {
            'title': Path(filepath).stem.replace('_', ' ').replace('-', ' ').title(),
            'content': f"[Image: {Path(filepath).name} - OCR not available]"
        }

    try:
        from doctr.io import DocumentFile

        doc = DocumentFile.from_images(filepath)
        result = predictor(doc)

        text_parts = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    line_text = ' '.join(word.value for word in line.words)
                    text_parts.append(line_text)

        text = '\n'.join(text_parts)
        title = Path(filepath).stem.replace('_', ' ').replace('-', ' ').title()

        return {
            'title': title,
            'content': text.strip() if text.strip() else f"[Image: {Path(filepath).name}]"
        }
    except Exception as e:
        print(f"    → Image OCR error: {e}")
        return {
            'title': Path(filepath).stem.replace('_', ' ').replace('-', ' ').title(),
            'content': f"[Image: {Path(filepath).name}]"
        }

def load_docx(filepath):
    """Load a .docx Word document."""
    if not DOCX_SUPPORT:
        raise ImportError("python-docx not installed")

    doc = DocxDocument(filepath)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    content = '\n\n'.join(paragraphs)

    title = Path(filepath).stem.replace('_', ' ').replace('-', ' ').title()

    return {
        'title': title,
        'content': content.strip()
    }

# =============================================================================
# Chunking (split large documents for better retrieval)
# =============================================================================

def chunk_text(text, chunk_size=500, overlap=50):
    """
    Split text into smaller chunks.

    Why? Large documents don't embed well - the meaning gets diluted.
    Smaller chunks = more precise retrieval.

    Args:
        text: The full text
        chunk_size: Target characters per chunk
        overlap: Characters to overlap between chunks (preserves context)
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            for i in range(min(100, end - start)):
                check_pos = end - i
                if check_pos < len(text) and text[check_pos] in '.!?\n':
                    end = check_pos + 1
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks

# =============================================================================
# Main loader
# =============================================================================

def load_all_documents():
    """Load all documents from the data folder."""
    documents = []
    doc_id = 1

    # Supported extensions and their loaders
    loaders = {
        '.txt': load_txt,
        '.md': load_md,
        '.json': load_json_doc,
    }

    # Add PDF and DOCX if libraries are available
    if PDF_SUPPORT:
        loaders['.pdf'] = load_pdf
    if DOCX_SUPPORT:
        loaders['.docx'] = load_docx

    # Add image formats (docTR will be lazy-loaded if needed)
    loaders['.jpg'] = load_image
    loaders['.jpeg'] = load_image
    loaders['.png'] = load_image

    # Walk through all files in data folder
    for root, dirs, files in os.walk(DATA_FOLDER):
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            ext = Path(filename).suffix.lower()

            if ext in loaders:
                try:
                    doc_data = loaders[ext](filepath)
                    rel_path = os.path.relpath(filepath, DATA_FOLDER)
                    content = doc_data['content']

                    # Chunk large documents
                    chunks = chunk_text(content, chunk_size=500, overlap=50)

                    if len(chunks) == 1:
                        # Small document - keep as is
                        document = {
                            'id': str(doc_id),
                            'title': doc_data['title'],
                            'content': content,
                            'metadata': {
                                'source': rel_path,
                                'type': ext[1:],
                                'loaded': datetime.now().isoformat()
                            }
                        }
                        documents.append(document)
                        print(f"  Loaded: {rel_path} → \"{doc_data['title'][:40]}\"")
                        doc_id += 1
                    else:
                        # Large document - split into chunks
                        for i, chunk in enumerate(chunks):
                            document = {
                                'id': f"{doc_id}_{i+1}",
                                'title': f"{doc_data['title']} (Part {i+1}/{len(chunks)})",
                                'content': chunk,
                                'metadata': {
                                    'source': rel_path,
                                    'type': ext[1:],
                                    'chunk': i + 1,
                                    'total_chunks': len(chunks),
                                    'loaded': datetime.now().isoformat()
                                }
                            }
                            documents.append(document)
                        print(f"  Loaded: {rel_path} → \"{doc_data['title'][:40]}\" ({len(chunks)} chunks)")
                        doc_id += 1

                except Exception as e:
                    print(f"  Error loading {filename}: {e}")

    return documents

# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DOCUMENT LOADER")
    print("=" * 60)
    print()

    # Check if data folder has files
    files_in_folder = list(Path(DATA_FOLDER).glob('**/*'))
    files_in_folder = [f for f in files_in_folder if f.is_file()]

    if not files_in_folder:
        print(f"No files found in {DATA_FOLDER}")
        print()
        print("To add your documents:")
        print(f"  1. Create files in: {DATA_FOLDER}")
        print("  2. Supported formats: .txt, .md, .json, .pdf, .docx, .jpg, .png")
        print("  3. Run this script again")
        print()

        # Create a sample file
        sample_file = os.path.join(DATA_FOLDER, 'sample_note.txt')
        with open(sample_file, 'w') as f:
            f.write("""This is a sample note.

You can replace this with your own content.

Add your personal notes, journal entries, meeting notes,
project ideas, or any text you want to make searchable.

The RAG system will find relevant documents when you ask questions.""")
        print(f"Created sample file: {sample_file}")
        print("Run this script again to load it.")

    else:
        print(f"Found {len(files_in_folder)} files")
        print()
        print("Loading documents...")

        documents = load_all_documents()

        print()
        print(f"Loaded {len(documents)} document chunks")

        if documents:
            # Save to JSON
            os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(documents, f, indent=2, ensure_ascii=False)

            print(f"Saved to: {OUTPUT_FILE}")
            print()
            print("Next step: Run 'python rag.py' to search your documents")
        else:
            print("No documents loaded. Check your files.")

    print()
    print("=" * 60)
