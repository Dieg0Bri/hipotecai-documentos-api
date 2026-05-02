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

from fastapi import FastAPI, HTTPException
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
from src.models.schemas import ExtractFromGCSRequest, ExtractRequest  # noqa: E402
from src.services.text_extractor import extract_text_from_bytes  # noqa: E402
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


@app.post("/extract")
async def extract(req: ExtractRequest):
    try:
        extractor = get_extractor(req.tipo)
        result = extractor.extract(req.texto)

        if req.id_archivo and db:
            try:
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


@app.post("/extract-from-gcs")
async def extract_from_gcs(req: ExtractFromGCSRequest):
    if not storage_client:
        return error_response("GCS no inicializado", code="GCS_UNAVAILABLE", status_code=503)
    try:
        bucket = storage_client.bucket(settings.GCS_BUCKET_DOCUMENTOS)
        blob = bucket.blob(req.gcs_path)
        if not blob.exists():
            return error_response(f"Objeto no existe: {req.gcs_path}", code="OBJECT_NOT_FOUND", status_code=404)

        content = blob.download_as_bytes()
        text = extract_text_from_bytes(content, mime_type=blob.content_type, filename=req.gcs_path)
        if not text.strip():
            return error_response("PDF sin texto seleccionable.", code="NO_TEXT", status_code=422)

        extractor = get_extractor(req.tipo)
        result = extractor.extract(text)

        if req.id_archivo and db:
            try:
                await db.save_extraction(
                    id_archivo=req.id_archivo,
                    tipo=req.tipo,
                    datos=result.datos,
                    confianza=result.confianza,
                    spans=result.spans,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Persist failed: %s", exc)

        return success_response(
            data={"folio": req.folio, "gcs_path": req.gcs_path, "extraccion": result.model_dump()},
            message=f"Documento {req.tipo} procesado.",
        )
    except ValueError as exc:
        return error_response(str(exc), code="UNKNOWN_TYPE", status_code=400)
    except NotImplementedError as exc:
        return error_response(str(exc), code="UNSUPPORTED_FORMAT", status_code=415)
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract-from-gcs error")
        return error_response(str(exc), code="EXTRACT_FAILED")
