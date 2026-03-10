"""Tests for load_documents chunking (chunk_text, chunk_text_smart)."""
import pytest
from load_documents import chunk_text, chunk_text_smart


def test_chunk_text_short():
    """Short text below chunk_size returns single chunk."""
    out = chunk_text("Hello world", chunk_size=500, overlap=50)
    assert out == ["Hello world"]


def test_chunk_text_splits():
    """Long text is split into multiple chunks with overlap."""
    text = "A. " + "word " * 200  # > 500 chars
    out = chunk_text(text, chunk_size=100, overlap=10)
    assert len(out) >= 2
    total = sum(len(c) for c in out)
    assert total >= len(text) - 150  # overlap may reduce total


def test_chunk_text_sentence_boundary():
    """Chunking tries to break at sentence boundaries."""
    text = "First sentence. " + "x" * 400 + " Second sentence. " + "y" * 100
    out = chunk_text(text, chunk_size=200, overlap=20)
    assert any("First sentence" in c for c in out)
    assert any("Second sentence" in c for c in out)


def test_chunk_text_smart_plain_fallback():
    """chunk_text_smart with is_markdown=False behaves like chunk_text."""
    text = "Plain text " * 80
    out = chunk_text_smart(text, chunk_size=100, overlap=10, is_markdown=False)
    assert len(out) >= 2
    assert "".join(out).replace(" ", "") == text.replace(" ", "")


def test_chunk_text_smart_markdown_sections():
    """Markdown with ## headers is split by section."""
    text = """# Title
Intro paragraph.

## Section One
Content for section one here.

## Section Two
Content for section two."""
    out = chunk_text_smart(text, chunk_size=50, overlap=5, is_markdown=True)
    assert len(out) >= 2
    joined = " ".join(out)
    assert "Section One" in joined or "section one" in joined
    assert "Section Two" in joined or "section two" in joined


def test_chunk_text_smart_markdown_no_headers():
    """Markdown without ## falls back to normal chunking."""
    text = "No headers here. " + "word " * 100
    out = chunk_text_smart(text, chunk_size=80, overlap=10, is_markdown=True)
    assert len(out) >= 2
