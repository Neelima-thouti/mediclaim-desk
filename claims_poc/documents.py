"""Turn uploaded file bytes into text. Scanned images need OCR (see README), so they return None."""
from __future__ import annotations

import io
from typing import Optional


def bytes_to_text(filename: str, data: bytes) -> Optional[str]:
    name = filename.lower()
    if name.endswith(".txt"):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()
        return text or None  # a scanned PDF has no text layer
    return None
