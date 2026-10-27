"""Chunking: cut a long document into pieces a retriever can find and a model can read."""
from __future__ import annotations

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


def chunk_policy(markdown_text: str, chunk_size: int = 500, chunk_overlap: int = 60) -> list[dict]:
    """Structure-aware chunking.
    Step 1: split on the document's own headings, so a clause is never mixed with another clause.
    Step 2: if a section is still too long, split it by size, preferring paragraph and sentence breaks.
    Each chunk keeps its heading path as metadata, so a retrieved chunk can be cited."""
    by_heading = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "document"), ("##", "clause")], strip_headers=False)
    sections = by_heading.split_text(markdown_text)
    by_size = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    pieces = by_size.split_documents(sections)
    return [{"id": f"chunk-{i:03d}", "text": p.page_content, "metadata": dict(p.metadata)}
            for i, p in enumerate(pieces)]


def naive_chunks(text: str, size: int = 300) -> list[str]:
    """The beginner approach: cut every N characters. Used in the tutorial to show what goes wrong."""
    return [text[i:i + size] for i in range(0, len(text), size)]
