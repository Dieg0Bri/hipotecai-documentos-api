"""
Extracción de texto de PDFs/imágenes con soporte de OCR por página.

El caso típico chileno es un documento mixto: la primera página es una
carátula notarial generada digitalmente (texto seleccionable) y desde la
página 2 viene la escritura escaneada. Este módulo extrae cada página por
separado y marca las vacías para que el caller decida qué páginas mandar
a OCR — sin tirar a la basura el texto digital ya disponible.
"""
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class PageOffset(NamedTuple):
    """Offset de una página dentro del texto concatenado.

    `start` y `end` son índices de carácter en el string completo.
    """
    page: int        # 1-based
    start: int
    end: int


@dataclass
class PageContent:
    """Contenido de una página antes del ensamblaje final.

    `source` permite trazar de dónde vino el texto en cada página y por lo
    tanto qué clase de evidencia respaldan los campos extraídos en ella.
    Una mezcla pdf_text+ocr es legítima: una escritura con carátula notarial
    digital + cuerpo escaneado.

    Cuando `source == 'ocr'`, `id_ocr` apunta a la fila de dt_ocr_resultado
    que contiene la transcripción con bbox + confidence — la evidencia legal
    se ata ahí, no al texto inline.
    `confianza_ocr_promedio` es el promedio de confidence de las líneas Surya
    en esa página, útil para alertar al letrado de páginas dudosas.
    """
    page: int                          # 1-based
    text: str                          # "" si no se pudo extraer
    source: str = "empty"              # "pdf_text" | "ocr" | "empty"
    id_ocr: int | None = None
    confianza_ocr_promedio: float | None = None


# Heurística: una página con menos de este número de caracteres alfanuméricos
# se considera "esencialmente vacía" — típicamente porque pdfplumber sólo
# capturó número de página o sello difuso. Ajustable por env si hace falta.
_EMPTY_PAGE_THRESHOLD = 20


def _is_effectively_empty(text: str) -> bool:
    if not text:
        return True
    alnum = sum(1 for c in text if c.isalnum())
    return alnum < _EMPTY_PAGE_THRESHOLD


def extract_pages_from_pdf(content: bytes, max_pages: int = 60) -> list[PageContent]:
    """Devuelve UNA entrada por página (incluso vacías) hasta `max_pages`."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber no instalado") from exc

    pages: list[PageContent] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            text = (page.extract_text() or "").strip()
            if _is_effectively_empty(text):
                pages.append(PageContent(page=i + 1, text="", source="empty"))
            else:
                pages.append(PageContent(page=i + 1, text=text, source="pdf_text"))
    return pages


def extract_pages_from_bytes(
    content: bytes, mime_type: str | None = None, filename: str | None = None
) -> list[PageContent]:
    ext = (Path(filename).suffix.lower() if filename else "")
    if (mime_type and "pdf" in mime_type) or ext == ".pdf":
        return extract_pages_from_pdf(content)
    if (mime_type and mime_type.startswith("text/")) or ext in {".txt", ".md"}:
        text = content.decode("utf-8", errors="ignore")
        return [PageContent(page=1, text=text, source="pdf_text" if text.strip() else "empty")]
    if (mime_type and mime_type.startswith("image/")) or ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        # Imagen suelta: se delega 100% a OCR.
        return [PageContent(page=1, text="", source="empty")]
    raise NotImplementedError(f"Formato no soportado: {mime_type} {ext}")


def assemble_text_and_offsets(pages: list[PageContent]) -> tuple[str, list[PageOffset]]:
    """Concatena las páginas no vacías con '\\n\\n' y devuelve los offsets.

    Las páginas con `text == ""` simplemente se omiten — no hay nada que
    indexar. El número de página real se preserva en el PageOffset.
    """
    SEP = "\n\n"
    parts: list[str] = []
    offsets: list[PageOffset] = []
    cursor = 0
    for p in pages:
        if not p.text:
            continue
        if parts:
            cursor += len(SEP)
        start = cursor
        end = cursor + len(p.text)
        offsets.append(PageOffset(page=p.page, start=start, end=end))
        parts.append(p.text)
        cursor = end
    return SEP.join(parts), offsets


def page_for_offset(offsets: list[PageOffset], char_pos: int | None) -> int | None:
    if char_pos is None:
        return None
    for off in offsets:
        if off.start <= char_pos < off.end:
            return off.page
    return None


# ───── Compatibilidad con el contrato anterior ─────

def extract_text_from_pdf(content: bytes, max_pages: int = 30) -> str:
    pages = extract_pages_from_pdf(content, max_pages=max_pages)
    text, _ = assemble_text_and_offsets(pages)
    return text


def extract_text_with_pages(
    content: bytes, max_pages: int = 30
) -> tuple[str, list[PageOffset]]:
    pages = extract_pages_from_pdf(content, max_pages=max_pages)
    return assemble_text_and_offsets(pages)


def extract_text_from_bytes(content: bytes, mime_type: str | None = None, filename: str | None = None) -> str:
    pages = extract_pages_from_bytes(content, mime_type=mime_type, filename=filename)
    text, _ = assemble_text_and_offsets(pages)
    return text


def extract_text_with_pages_from_bytes(
    content: bytes, mime_type: str | None = None, filename: str | None = None
) -> tuple[str, list[PageOffset]]:
    pages = extract_pages_from_bytes(content, mime_type=mime_type, filename=filename)
    return assemble_text_and_offsets(pages)
