"""
documentos-api · FastAPI principal
--------------------------------------------------------------
Endpoints:
  GET  /health
  POST /extract                 ← extrae campos por tipo dado el texto
  POST /extract-from-gcs        ← descarga, extrae texto, extrae campos, persiste
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import settings  # noqa: E402
from src.core.structured_logging import configure_logging  # noqa: E402
from src.database.cloudsql_handler import CloudSQLHandler  # noqa: E402
from src.extractors import get_extractor  # noqa: E402
from src.middleware.analytics import AnalyticsMiddleware  # noqa: E402
from src.middleware.oauth import GoogleOAuthMiddleware  # noqa: E402
from src.models.schemas import (  # noqa: E402
    CreateAnchorRequest,
    ExtractFromGCSRequest,
    ExtractRequest,
    UpdateAnchorRequest,
)
from src.services.text_extractor import (  # noqa: E402
    PageContent,
    assemble_text_and_offsets,
    extract_pages_from_bytes,
    page_for_offset,
)
from src.utils.responses import error_response, success_response  # noqa: E402


configure_logging()
logger = logging.getLogger(__name__)

storage_client: Optional[storage.Client] = None
db: Optional[CloudSQLHandler] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global storage_client, db

    logger.info("Starting documentos-api...")

    try:
        storage_client = storage.Client()
        logger.info("GCS ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("GCS failed: %s", exc)

    db = CloudSQLHandler()
    try:
        await db.initialize()
        if await db.health_check():
            logger.info("CloudSQL ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CloudSQL failed: %s", exc)

    yield
    if db:
        await db.close()


app = FastAPI(
    title="documentos-api",
    description="Extracción estructurada de campos legales por tipo de documento.",
    version=settings.SERVICE_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
app.add_middleware(AnalyticsMiddleware)
app.add_middleware(GoogleOAuthMiddleware)


@app.get("/health")
async def health():
    db_ok = await db.health_check() if db else False
    return success_response(
        data={
            "service": settings.SERVICE_NAME,
            "version": settings.SERVICE_VERSION,
            "database": "ok" if db_ok else "error",
            "gemini_configured": bool(settings.GEMINI_API_KEY),
        }
    )


EXTRACTION_PIPELINE_VERSION = "v1"


def _build_evidencia(
    spans: list,
    page_offsets: list,
    text: str,
    pages_local: list,
) -> list[dict]:
    """Convierte los spans de langextract en filas para dt_extraccion_evidencia.

    Crucial: si la página de origen del span vino de OCR, la evidencia se
    etiqueta `fuente_texto='ocr'` y se ata vía `id_ocr` al artefacto OCR
    en dt_ocr_resultado. Sin esto el abogado no podría distinguir un campo
    extraído del texto nativo del PDF (autoridad alta) de uno extraído de
    una transcripción de modelo (probabilística).

    Para OCR adicionalmente resolvemos las bboxes de las lineas Surya que
    overlapean el span (en coords PDF). Esto permite al frontend dibujar
    el highlight directo sobre el canvas sin depender del text-layer.
    """
    page_meta = {p.page: p for p in pages_local}
    # Indice page→global_start para mapear span_global a span_local_de_pagina.
    page_global_start = {o.page: o.start for o in (page_offsets or [])}
    evidencia: list[dict] = []
    for span in spans or []:
        cs = span.get("start_char")
        ce = span.get("end_char")
        snippet = span.get("value")
        if snippet is None and cs is not None and ce is not None:
            snippet = text[cs:ce]
        page_num = page_for_offset(page_offsets, cs)
        page_obj = page_meta.get(page_num) if page_num else None

        is_ocr = bool(page_obj and page_obj.source == "ocr")
        bboxes = _bboxes_for_span(
            cs, ce, page_num, page_obj, page_global_start,
        ) if is_ocr else None
        evidencia.append({
            "campo": span.get("field"),
            "page": page_num,
            "char_start": cs,
            "char_end": ce,
            "snippet": snippet,
            "fuente_texto": "ocr" if is_ocr else "pdf_text",
            "id_ocr": page_obj.id_ocr if is_ocr else None,
            "confianza_ocr": page_obj.confianza_ocr_promedio if is_ocr else None,
            "bboxes": bboxes,
        })
    return evidencia


def _bboxes_for_span(
    cs_global: int | None,
    ce_global: int | None,
    page_num: int | None,
    page_obj,
    page_global_start: dict[int, int],
) -> list[list[float]] | None:
    """Encuentra las bboxes (en PT) de las lineas OCR que cubren un span.

    Convierte el span global del texto ensamblado a coordenadas locales
    de la pagina, despues itera las lineas buscando overlap. Una entity
    puede partirse en varias lineas (ej. nombre largo a 2 renglones); por
    eso devuelve lista.

    Devuelve None si:
    - El span carece de offsets validos
    - La pagina no esta en page_obj o page_obj.lines es vacio
    - Ninguna linea overlapea (caso raro, posible si langextract apunta a
      whitespace entre lineas)
    """
    if cs_global is None or ce_global is None or page_num is None:
        return None
    if not page_obj or not page_obj.lines:
        return None
    page_start_global = page_global_start.get(page_num)
    if page_start_global is None:
        return None
    cs_local = cs_global - page_start_global
    ce_local = ce_global - page_start_global
    if ce_local <= 0 or cs_local >= len(page_obj.text):
        return None
    bboxes: list[list[float]] = []
    for line in page_obj.lines:
        bbox = line.get("bbox")
        line_cs = line.get("char_start")
        line_ce = line.get("char_end")
        if bbox is None or line_cs is None or line_ce is None:
            continue
        # Overlap estricto. Esto evita matchear lineas vacias o whitespace.
        if line_cs < ce_local and line_ce > cs_local:
            bboxes.append(list(bbox))
    return bboxes or None


@app.post("/extract")
async def extract(req: ExtractRequest):
    try:
        extractor = get_extractor(req.tipo)
        result = extractor.extract(req.texto)

        if req.id_archivo and db:
            try:
                # En este path no tenemos el binario original — la evidencia con
                # sha256 verificable se persiste sólo desde /extract-from-gcs.
                await db.save_extraction(
                    id_archivo=req.id_archivo,
                    tipo=req.tipo,
                    datos=result.datos,
                    confianza=result.confianza,
                    spans=result.spans,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist extraction: %s", exc)

        return success_response(data=result.model_dump())
    except ValueError as exc:
        return error_response(str(exc), code="UNKNOWN_TYPE", status_code=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract error")
        return error_response(str(exc), code="EXTRACT_FAILED")


@app.get("/archivos/{id_archivo}/ocr")
async def get_ocr_transcript(id_archivo: int, modelo: str | None = None):
    """Devuelve el documento OCR del archivo (URI al .md en GCS) + offsets
    por página + bbox/confidence por línea.

    **Importante**: el OCR NUNCA reemplaza al documento — vive como
    artefacto separado en su propio bucket. Este endpoint expone esa
    separación: el caller obtiene la URI al markdown y la firma vía
    `ingestion-service/api-ingestion/upload/ocr-download-url` (mismo
    servicio que firma el PDF original, mismo tenant scoping).
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    documento = await db.get_ocr_documento(id_archivo, modelo=modelo)
    if not documento:
        return success_response(data={"id_archivo": id_archivo, "documento": None, "paginas": []})
    paginas = await db.get_ocr_paginas(documento["id_ocr_documento"])
    return success_response(data={
        "id_archivo": id_archivo,
        "documento": documento,
        "paginas": paginas,
    })


@app.get("/extracciones/{id_extraccion}/evidencia")
async def get_evidencia_extraccion(id_extraccion: int):
    """Lista cada campo extraído con su evidencia (página, span, snippet) y
    fuente_texto (`pdf_text` vs `ocr`). Permite que la UI pinte un badge
    "vía OCR" en los campos que dependen de transcripción de modelo.

    Alias retrocompat de `/extracciones/{id}/anchors`. Devuelve el mismo
    shape, incluyendo los campos nuevos `origen` y `estado` (migración 010).
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    items = await db.list_anchors(id_extraccion)
    return success_response(data={"id_extraccion": id_extraccion, "evidencia": items})


# ─────────────────── CRUD de anchors (migración 010) ───────────────────
# Los anchors son la trazabilidad navegable entre un campo extraído y su
# ubicación en el documento. El extractor crea anchors `auto` y el abogado
# puede agregar/editar/borrar/confirmar/rechazar sobre ellos en el visor.
#
# Convenciones REST:
#   - El recurso colección vive bajo /extracciones/{id_extraccion}/anchors
#     porque crear un anchor sin contexto de extracción no tiene sentido.
#   - El recurso individual vive bajo /anchors/{id_anchor} (sin nested)
#     porque ahí ya conocemos su id_extraccion vía la PK y queremos URLs
#     cortas para PATCH/DELETE.
#   - DELETE de un anchor 'auto' hace soft (estado='rechazado') por
#     auditoría; DELETE de un 'manual' hace hard. Ver delete_anchor().

def _creador_actual(request) -> str:
    """Identifica al autor del cambio. Usa el email del JWT si está; cae
    a 'sistema' cuando se llama sin auth (modo dev / health probes)."""
    try:
        user = getattr(request.state, "user", None)
        if user and user.get("email"):
            return user["email"]
    except Exception:  # noqa: BLE001
        pass
    return "sistema"


@app.get("/extracciones/{id_extraccion}/anchors")
async def list_anchors(id_extraccion: int, include_rejected: bool = True):
    """Lista todos los anchors de una extracción.

    Por default incluye los rechazados — el frontend filtra según si está
    en modo "ver activos" o "ver auditoría". Para listar solo lo visible
    al abogado por default, pasar `?include_rejected=false`.
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    items = await db.list_anchors(id_extraccion, include_rejected=include_rejected)
    return success_response(data={"id_extraccion": id_extraccion, "anchors": items})


@app.post("/extracciones/{id_extraccion}/anchors", status_code=201)
async def create_anchor(id_extraccion: int, req: CreateAnchorRequest, request: Request):
    """Crea un anchor MANUAL. Nace con estado='confirmado' porque la acción
    de crearlo a mano implica que el abogado ya validó la ubicación.

    Valida coherencia mínima: si `fuente_texto='ocr'` debe traer bboxes;
    si `'pdf_text'` debe traer char_start/char_end.
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    # Page es obligatorio — sin él no podemos pintar el anchor en ningún lado.
    if req.page is None:
        return error_response(
            "page es obligatorio para crear un anchor.",
            code="MISSING_PAGE", status_code=422,
        )
    # Ubicación: bboxes (preferido para anchors manuales del frontend, porque
    # se calculan client-side via getClientRects/rect drawing) o char_start +
    # char_end (legacy / extraction auto). Necesitamos al menos uno.
    has_bboxes = bool(req.bboxes)
    has_char_range = req.char_start is not None and req.char_end is not None
    if not has_bboxes and not has_char_range:
        return error_response(
            "Anchor requiere bboxes o char_start+char_end. El frontend "
            "típicamente envía bboxes desde la selección/dibujo.",
            code="MISSING_LOCATION", status_code=422,
        )
    try:
        anchor = await db.create_anchor(
            id_extraccion=id_extraccion,
            campo=req.campo,
            page=req.page,
            char_start=req.char_start,
            char_end=req.char_end,
            snippet=req.snippet,
            fuente_texto=req.fuente_texto,
            bboxes=req.bboxes,
            id_ocr=req.id_ocr,
            creado_por=_creador_actual(request),
        )
        return success_response(data=anchor, message="Anchor creado.")
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_INPUT", status_code=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_anchor")
        return error_response(str(exc), code="CREATE_FAILED")


@app.patch("/anchors/{id_anchor}")
async def update_anchor(id_anchor: str, req: UpdateAnchorRequest):
    """Edita un anchor existente. Cualquier campo no provisto se preserva.

    Para mover el anchor a otro span, pasar campos `page` + `char_start` +
    `char_end` (pdf_text) o `bboxes` (ocr). Para cambiar el estado, pasar
    `estado` — la UI normalmente usa esto para Confirmar/Rechazar.

    Compat: a partir de la migración 011, rechazar es hard-delete. Si el
    cliente manda `estado='rechazado'`, redirigimos a delete y devolvemos
    el shape de DeleteAnchorResult (`{id_anchor, action: 'deleted'}`) para
    que el cliente sepa que el recurso ya no existe.
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    if req.estado == "rechazado":
        action = await db.delete_anchor(id_anchor)
        if action is None:
            return error_response("Anchor no existe", code="NOT_FOUND", status_code=404)
        return success_response(data={"id_anchor": id_anchor, "action": action})
    try:
        anchor = await db.update_anchor(
            id_anchor,
            campo=req.campo,
            snippet=req.snippet,
            estado=req.estado,
            page=req.page,
            char_start=req.char_start,
            char_end=req.char_end,
            bboxes=req.bboxes,
            # clear_bboxes y bboxes son mutuamente excluyentes en sentido
            # semántico; pasamos bboxes_set=True si el cliente envió
            # `clear_bboxes=true` o si envió un array explícito.
            bboxes_set=req.clear_bboxes or req.bboxes is not None,
        )
        if not anchor:
            return error_response("Anchor no existe", code="NOT_FOUND", status_code=404)
        return success_response(data=anchor)
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_INPUT", status_code=400)


@app.delete("/anchors/{id_anchor}")
async def delete_anchor(id_anchor: str):
    """Hard delete: remueve el anchor del blob de la extracción.

    A partir de la migración 011 no hay soft-delete — origen 'auto' o
    'manual', ambos se borran físicamente. Si el extractor vuelve a
    proponer un anchor borrado en un reproceso, reaparece con nuevo UUID.
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    action = await db.delete_anchor(id_anchor)
    if action is None:
        return error_response("Anchor no existe", code="NOT_FOUND", status_code=404)
    return success_response(data={"id_anchor": id_anchor, "action": action})


@app.post("/anchors/{id_anchor}/confirmar")
async def confirmar_anchor(id_anchor: str):
    """Shortcut de PATCH estado='confirmado'. La UI lo llama desde el botón
    'Aprobar' del panel de entidades."""
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    anchor = await db.update_anchor(id_anchor, estado="confirmado")
    if not anchor:
        return error_response("Anchor no existe", code="NOT_FOUND", status_code=404)
    return success_response(data=anchor)


@app.post("/anchors/{id_anchor}/rechazar")
async def rechazar_anchor(id_anchor: str):
    """Rechazar = borrar el anchor (modelo 011 no tiene soft-delete).
    Se mantiene el endpoint por compat: el cliente puede seguir llamando
    /rechazar pero el efecto es idéntico a DELETE.
    """
    if not db:
        return error_response("DB no inicializada", code="NOT_READY", status_code=503)
    action = await db.delete_anchor(id_anchor)
    if action is None:
        return error_response("Anchor no existe", code="NOT_FOUND", status_code=404)
    return success_response(data={"id_anchor": id_anchor, "action": action})


async def _load_pages_from_pdf(content: bytes, blob_content_type: str, gcs_path: str) -> list[PageContent]:
    """Path 'pdf_text': extracción nativa via pdfplumber, todas las páginas
    son source='pdf_text'. Toda evidencia se etiquetará como pdf_text."""
    return extract_pages_from_bytes(content, mime_type=blob_content_type, filename=gcs_path)


async def _load_pages_from_ocr(
    bucket: str, gcs_path_md: str, paginas_meta: list[dict],
) -> list[PageContent]:
    """Path 'ocr': descarga el .md del bucket OCR y reconstruye PageContent[]
    usando los offsets que persistió ocr-api en dt_ocr_pagina.

    Cada PageContent queda con source='ocr' + id_ocr (FK a dt_ocr_pagina) +
    `lines` (con bbox en PT y char_start/char_end locales) → el
    evidence-builder etiqueta la evidencia como OCR y calcula bboxes por
    overlap span↔linea.
    """
    if not storage_client:
        raise RuntimeError("GCS no inicializado para descargar OCR markdown")
    blob = storage_client.bucket(bucket).blob(gcs_path_md)
    md_bytes = blob.download_as_bytes()
    md = md_bytes.decode("utf-8", errors="replace")

    pages: list[PageContent] = []
    for meta in paginas_meta:
        cs = meta["char_start"]
        ce = meta["char_end"]
        page_text = md[cs:ce]
        if not page_text.strip():
            continue
        pages.append(PageContent(
            page=meta["pagina"],
            text=page_text,
            source="ocr",
            id_ocr=meta["id_ocr_pagina"],
            confianza_ocr_promedio=float(meta["confianza_promedio"])
                if meta.get("confianza_promedio") is not None else None,
            # lines viene como JSONB de Postgres → list[dict] en Python.
            # Cada item tiene char_start/char_end relativos al texto de la
            # pagina (NO al markdown completo) — ojo no confundir cuando
            # esto se cruza con offsets globales.
            lines=meta.get("lines"),
        ))
    return pages


@app.post("/extract-from-gcs")
async def extract_from_gcs(req: ExtractFromGCSRequest):
    import hashlib
    import time

    if not storage_client:
        return error_response("GCS no inicializado", code="GCS_UNAVAILABLE", status_code=503)
    try:
        bucket = storage_client.bucket(settings.GCS_BUCKET_DOCUMENTOS)
        blob = bucket.blob(req.gcs_path)
        if not blob.exists():
            return error_response(f"Objeto no existe: {req.gcs_path}", code="OBJECT_NOT_FOUND", status_code=404)

        content = blob.download_as_bytes()
        sha256_documento = hashlib.sha256(content).hexdigest()

        # Idempotencia (#6): si ya extrajimos exitosamente este (archivo, sha,
        # versión) devolvemos OK sin re-pegarle a Gemini.
        if req.id_archivo and db:
            already = await db.pipeline_run_already_ok(
                id_archivo=req.id_archivo,
                etapa="extraccion",
                sha256_input=sha256_documento,
                version=EXTRACTION_PIPELINE_VERSION,
            )
            if already:
                return success_response(
                    data={"folio": req.folio, "gcs_path": req.gcs_path,
                          "skipped": True, "reason": "already_processed"},
                    message="Idempotente: ya procesado para este sha256.",
                )

        # Decisión de fuente (la tomó el clasificador, #008). El extractor NO
        # mezcla — usa pdf_text O ocr, nunca ambos.
        fuente = "pdf_text"
        ocr_documento_meta: dict | None = None
        paginas_meta: list[dict] = []
        if req.id_archivo and db:
            src_info = await db.get_extraction_source(req.id_archivo)
            if src_info:
                fuente = src_info.get("fuente_extraccion") or "pdf_text"
                if fuente == "ocr":
                    estado = src_info.get("estado_ocr")
                    if estado != "listo":
                        return error_response(
                            f"OCR no está listo para este archivo (estado={estado}). "
                            "Re-clasificar o esperar a que termine el job OCR.",
                            code="OCR_PENDIENTE",
                            status_code=409,
                        )
                    if not src_info.get("id_ocr_documento"):
                        return error_response(
                            "Archivo marcado fuente_extraccion='ocr' pero no hay "
                            "dt_ocr_documento asociado. Re-clasificar.",
                            code="OCR_FALTA_DOCUMENTO", status_code=409,
                        )
                    ocr_documento_meta = src_info
                    paginas_meta = await db.get_ocr_paginas_with_offsets(
                        src_info["id_ocr_documento"],
                    )

        # Cargar PageContent[] de UNA sola fuente.
        if fuente == "ocr" and ocr_documento_meta:
            pages_local = await _load_pages_from_ocr(
                bucket=ocr_documento_meta["gcs_bucket"],
                gcs_path_md=ocr_documento_meta["gcs_path"],
                paginas_meta=paginas_meta,
            )
            ocr_pages_used = [p.page for p in pages_local]
        else:
            pages_local = await _load_pages_from_pdf(content, blob.content_type, req.gcs_path)
            ocr_pages_used = []

        text, page_offsets = assemble_text_and_offsets(pages_local)

        if not text.strip():
            return error_response(
                "Documento sin texto extractable.", code="NO_TEXT", status_code=422,
            )

        started = time.monotonic()
        extractor = get_extractor(req.tipo)
        result = extractor.extract(text)
        duracion_ms = int((time.monotonic() - started) * 1000)

        evidencia = _build_evidencia(result.spans or [], page_offsets, text, pages_local)

        if req.id_archivo and db:
            try:
                await db.save_extraction(
                    id_archivo=req.id_archivo,
                    tipo=req.tipo,
                    datos=result.datos,
                    confianza=result.confianza,
                    spans=result.spans,
                    evidencia=evidencia,
                    sha256_documento=sha256_documento,
                )
                await db.pipeline_run_record(
                    id_archivo=req.id_archivo,
                    etapa="extraccion",
                    sha256_input=sha256_documento,
                    version=EXTRACTION_PIPELINE_VERSION,
                    estado="ok",
                    duracion_ms=duracion_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Persist failed: %s", exc)
                if req.id_archivo and db:
                    try:
                        await db.pipeline_run_record(
                            id_archivo=req.id_archivo,
                            etapa="extraccion",
                            sha256_input=sha256_documento,
                            version=EXTRACTION_PIPELINE_VERSION,
                            estado="error",
                            duracion_ms=duracion_ms,
                            error_msg=str(exc),
                        )
                    except Exception:  # noqa: BLE001
                        pass

        return success_response(
            data={
                "folio": req.folio,
                "gcs_path": req.gcs_path,
                "sha256_documento": sha256_documento,
                "fuente_extraccion": fuente,           # 'pdf_text' o 'ocr'
                "ocr_pages_used": ocr_pages_used,
                "evidencia_count": len(evidencia),
                "extraccion": result.model_dump(),
            },
            message=f"Documento {req.tipo} procesado (fuente={fuente}).",
        )
    except ValueError as exc:
        return error_response(str(exc), code="UNKNOWN_TYPE", status_code=400)
    except NotImplementedError as exc:
        return error_response(str(exc), code="UNSUPPORTED_FORMAT", status_code=415)
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract-from-gcs error")
        return error_response(str(exc), code="EXTRACT_FAILED")
