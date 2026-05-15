"""CloudSQLHandler — persiste extracciones en dt_extraccion."""
import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import text

from src.core.config import settings

logger = logging.getLogger(__name__)


class CloudSQLHandler:
    def __init__(self):
        self.engine: Optional[AsyncEngine] = None
        self.session_factory = None

    def _build_url(self) -> str:
        if os.environ.get("K_SERVICE") and settings.INSTANCE_CONNECTION_NAME:
            return (
                f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@/{settings.DB_NAME}?host=/cloudsql/{settings.INSTANCE_CONNECTION_NAME}"
            )
        return (
            f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}"
            f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
        )

    async def initialize(self):
        self.engine = create_async_engine(self._build_url(), pool_pre_ping=True, pool_size=5)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        logger.info("CloudSQL initialized")

    async def health_check(self) -> bool:
        if not self.engine:
            return False
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("CloudSQL health check failed: %s", exc)
            return False

    async def save_extraction(
        self,
        *,
        id_archivo: int,
        tipo: str,
        datos: dict,
        confianza: float,
        spans: list,
        evidencia: list[dict] | None = None,
        sha256_documento: str | None = None,
    ):
        """Persiste la extracción y, si se entregó, las filas de evidencia.

        `evidencia` es una lista de dicts con shape:
            { "campo": str, "page": int|None, "char_start": int|None,
              "char_end": int|None, "snippet": str|None,
              "confianza": float|None }
        Cada fila se ancla al sha256_documento provisto — si después se
        re-procesa el archivo con un PDF distinto, las evidencias viejas
        quedan invalidadas porque su sha no coincide con el archivo actual.
        """
        import json

        ins_extraccion = text(
            """
            INSERT INTO dt_extraccion (
                id_tenant, id_archivo, schema_codigo, datos, spans, confianza, fecha
            )
            SELECT a.id_tenant, :id_archivo, :schema,
                   CAST(:datos AS JSONB), CAST(:spans AS JSONB), :confianza, NOW()
            FROM dt_archivos a WHERE a.id_archivo = :id_archivo
            ON CONFLICT (id_archivo, schema_codigo) DO UPDATE SET
                datos = EXCLUDED.datos,
                spans = EXCLUDED.spans,
                confianza = EXCLUDED.confianza,
                fecha = NOW()
            RETURNING id_extraccion, id_tenant
            """
        )
        async with self.session_factory() as session:
            result = await session.execute(ins_extraccion, {
                "id_archivo": id_archivo,
                "schema": tipo,
                "datos": json.dumps(datos, ensure_ascii=False),
                "spans": json.dumps(spans, ensure_ascii=False),
                "confianza": confianza,
            })
            row = result.first()
            id_extraccion = row[0] if row else None
            id_tenant = row[1] if row else None

            # Reemplazar evidencia anterior cuando re-procesamos:
            # un sha distinto invalida cualquier evidencia previa.
            if id_extraccion and evidencia is not None:
                await session.execute(
                    text("DELETE FROM dt_extraccion_evidencia WHERE id_extraccion = :id"),
                    {"id": id_extraccion},
                )
                if evidencia and sha256_documento:
                    ins_ev = text(
                        """
                        INSERT INTO dt_extraccion_evidencia (
                            id_tenant, id_extraccion, id_archivo, campo, page,
                            char_start, char_end, snippet, sha256_documento, confianza,
                            fuente_texto, id_ocr, confianza_ocr, bboxes
                        )
                        VALUES (
                            :id_tenant, :id_extraccion, :id_archivo, :campo, :page,
                            :char_start, :char_end, :snippet, :sha, :confianza,
                            :fuente_texto, :id_ocr, :confianza_ocr,
                            CAST(:bboxes AS JSONB)
                        )
                        """
                    )
                    for ev in evidencia:
                        bboxes = ev.get("bboxes")
                        await session.execute(ins_ev, {
                            "id_tenant": id_tenant,
                            "id_extraccion": id_extraccion,
                            "id_archivo": id_archivo,
                            "campo": ev.get("campo"),
                            "page": ev.get("page"),
                            "char_start": ev.get("char_start"),
                            "char_end": ev.get("char_end"),
                            "snippet": (ev.get("snippet") or "")[:500] or None,
                            "sha": sha256_documento,
                            "confianza": ev.get("confianza"),
                            "fuente_texto": ev.get("fuente_texto", "pdf_text"),
                            "id_ocr": ev.get("id_ocr"),
                            "confianza_ocr": ev.get("confianza_ocr"),
                            "bboxes": json.dumps(bboxes) if bboxes else None,
                        })

            await session.execute(
                text("UPDATE dt_archivos SET estado_procesamiento = 'procesado', fecha_actualizacion = NOW() WHERE id_archivo = :id"),
                {"id": id_archivo},
            )
            await session.commit()
            return id_extraccion

    async def get_ocr_documento(self, id_archivo: int, modelo: str | None = None) -> dict | None:
        """Devuelve el último documento OCR (URI al .md + metadata global).

        El TEXTO completo NO está en la BBDD — vive como markdown en GCS.
        El frontend pide gcs_uri y luego ocr-api/ocr-document-url para
        firmar el link de descarga.
        """
        if not self.engine:
            return None
        sql = """
            SELECT id_ocr_documento, id_archivo, sha256_documento, modelo, formato,
                   gcs_bucket, gcs_path, gcs_uri, bytes, sha256_ocr,
                   paginas, confianza_promedio, fecha
            FROM dt_ocr_documento
            WHERE id_archivo = :id_archivo
        """
        params: dict = {"id_archivo": id_archivo}
        if modelo:
            sql += " AND modelo = :modelo"
            params["modelo"] = modelo
        sql += " ORDER BY fecha DESC LIMIT 1"

        async with self.session_factory() as session:
            res = await session.execute(text(sql), params)
            row = res.mappings().first()
            return dict(row) if row else None

    async def get_ocr_paginas(self, id_ocr_documento: int) -> list[dict]:
        """Páginas con offsets dentro del .md y bbox/confidence por línea.
        Usado por la UI para resaltar bbox sobre la imagen del PDF.
        """
        if not self.engine:
            return []
        async with self.session_factory() as session:
            res = await session.execute(
                text(
                    """
                    SELECT id_ocr_pagina, pagina, char_start, char_end,
                           confianza_promedio, lines
                    FROM dt_ocr_pagina
                    WHERE id_ocr_documento = :id
                    ORDER BY pagina ASC
                    """
                ),
                {"id": id_ocr_documento},
            )
            return [dict(r) for r in res.mappings().all()]

    async def get_evidencia(self, id_extraccion: int) -> list[dict]:
        """Devuelve evidencia de una extracción con la procedencia (pdf_text/ocr)
        para que el frontend muestre el badge correcto en cada campo. Cuando
        la evidencia es OCR, también devuelve gcs_uri al .md para enlazar.
        """
        if not self.engine:
            return []
        async with self.session_factory() as session:
            res = await session.execute(
                text(
                    """
                    SELECT e.id_evidencia, e.campo, e.page, e.char_start, e.char_end,
                           e.snippet, e.sha256_documento, e.confianza,
                           e.fuente_texto, e.id_ocr, e.confianza_ocr, e.bboxes,
                           op.id_ocr_documento, doc.modelo AS ocr_modelo,
                           doc.gcs_uri AS ocr_md_uri,
                           op.char_start AS ocr_pagina_char_start,
                           op.char_end   AS ocr_pagina_char_end
                    FROM dt_extraccion_evidencia e
                    LEFT JOIN dt_ocr_pagina op  ON op.id_ocr_pagina    = e.id_ocr
                    LEFT JOIN dt_ocr_documento doc ON doc.id_ocr_documento = op.id_ocr_documento
                    WHERE e.id_extraccion = :id_extraccion
                    ORDER BY e.page NULLS LAST, e.char_start NULLS LAST
                    """
                ),
                {"id_extraccion": id_extraccion},
            )
            rows = res.mappings().all()
            return [dict(row) for row in rows]

    async def get_archivo_sha256(self, id_archivo: int) -> str | None:
        """Lee el sha256 con el que el archivo quedó registrado en la ingesta."""
        if not self.engine:
            return None
        async with self.session_factory() as session:
            res = await session.execute(
                text("SELECT sha256 FROM dt_archivos WHERE id_archivo = :id"),
                {"id": id_archivo},
            )
            row = res.first()
            return row[0] if row else None

    async def get_extraction_source(self, id_archivo: int) -> dict | None:
        """Devuelve qué fuente debe usar el extractor según la decisión que
        tomó el clasificador (#008). Si fuente='ocr' incluye también la URI
        al markdown y los offsets por página para reconstruir las PageContent.
        """
        if not self.engine:
            return None
        async with self.session_factory() as session:
            res = await session.execute(
                text(
                    """
                    SELECT a.fuente_extraccion, a.estado_ocr, a.requiere_ocr,
                           a.razon_ocr, a.sha256,
                           doc.id_ocr_documento, doc.gcs_bucket, doc.gcs_path,
                           doc.gcs_uri, doc.modelo
                    FROM dt_archivos a
                    LEFT JOIN dt_ocr_documento doc
                      ON doc.id_archivo = a.id_archivo
                     AND doc.sha256_documento = a.sha256
                    WHERE a.id_archivo = :id
                    ORDER BY doc.fecha DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"id": id_archivo},
            )
            row = res.mappings().first()
            return dict(row) if row else None

    async def get_ocr_paginas_with_offsets(self, id_ocr_documento: int) -> list[dict]:
        """Para reconstruir PageContent[] desde el markdown OCR.

        Devuelve tambien `lines` (JSONB) para que `_build_evidencia()` pueda
        resolver el overlap span↔linea y calcular las bboxes de cada
        evidencia. Cada item en lines tiene shape:
            {text, bbox, confidence, char_start, char_end}
        donde char_start/char_end son offsets relativos a `page_text`
        (NO al markdown completo) y bbox esta en puntos PDF.
        """
        if not self.engine:
            return []
        async with self.session_factory() as session:
            res = await session.execute(
                text(
                    """
                    SELECT id_ocr_pagina, pagina, char_start, char_end,
                           confianza_promedio, lines
                    FROM dt_ocr_pagina
                    WHERE id_ocr_documento = :id
                    ORDER BY pagina ASC
                    """
                ),
                {"id": id_ocr_documento},
            )
            return [dict(r) for r in res.mappings().all()]

    # ───── Idempotencia de pipeline (#6) ─────

    async def pipeline_run_already_ok(
        self, *, id_archivo: int, etapa: str, sha256_input: str, version: str
    ) -> bool:
        """True si esta etapa ya corrió OK para este (archivo, sha, versión)."""
        if not self.engine:
            return False
        async with self.session_factory() as session:
            res = await session.execute(
                text(
                    """
                    SELECT 1 FROM dt_pipeline_run
                    WHERE id_archivo = :id AND etapa = :etapa
                      AND sha256_input = :sha AND version_pipeline = :version
                      AND estado = 'ok'
                    LIMIT 1
                    """
                ),
                {"id": id_archivo, "etapa": etapa, "sha": sha256_input, "version": version},
            )
            return res.first() is not None

    async def pipeline_run_record(
        self,
        *,
        id_archivo: int,
        etapa: str,
        sha256_input: str,
        version: str,
        estado: str,
        duracion_ms: int | None = None,
        error_msg: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Registra el resultado final de una etapa del pipeline.

        Usa ON CONFLICT contra el UNIQUE parcial — si ya existe una corrida 'ok'
        para esta clave no se inserta de nuevo. Filas en 'error' sí pueden
        coexistir con futuras corridas exitosas.
        """
        if not self.engine:
            return
        async with self.session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO dt_pipeline_run (
                        id_tenant, id_archivo, etapa, sha256_input, version_pipeline,
                        estado, duracion_ms, error_msg, request_id, started_at, finished_at
                    )
                    SELECT a.id_tenant, :id, :etapa, :sha, :version,
                           :estado, :dur, :err, :rid,
                           NOW() - (COALESCE(:dur,0) * INTERVAL '1 millisecond'), NOW()
                    FROM dt_archivos a WHERE a.id_archivo = :id
                    ON CONFLICT (id_archivo, etapa, sha256_input, version_pipeline, estado)
                    DO NOTHING
                    """
                ),
                {
                    "id": id_archivo, "etapa": etapa, "sha": sha256_input,
                    "version": version, "estado": estado, "dur": duracion_ms,
                    "err": (error_msg or "")[:1000] or None, "rid": request_id,
                },
            )
            await session.commit()

    async def close(self):
        if self.engine:
            await self.engine.dispose()
