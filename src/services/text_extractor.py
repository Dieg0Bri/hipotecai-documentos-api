"""Extracción de texto idéntica a la de clasificador-api."""
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(content: bytes, max_pages: int = 30) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber no instalado") from exc

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            text_parts.append((page.extract_text() or "").strip())
    return "\n\n".join(t for t in text_parts if t)


def extract_text_from_bytes(content: bytes, mime_type: str | None = None, filename: str | None = None) -> str:
    ext = (Path(filename).suffix.lower() if filename else "")
    if (mime_type and "pdf" in mime_type) or ext == ".pdf":
        return extract_text_from_pdf(content)
    if (mime_type and mime_type.startswith("text/")) or ext in {".txt", ".md"}:
        return content.decode("utf-8", errors="ignore")
    raise NotImplementedError(f"Formato no soportado: {mime_type} {ext}")
