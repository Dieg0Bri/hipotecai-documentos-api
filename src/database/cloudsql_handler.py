"""CloudSQLHandler — persiste extracciones en dt_extraccion."""
import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import text

from src.core.config import settings

logger = logging.getLogger(__name__)

# Etiqueta que queda en dt_extraccion_evidencia.creado_por para los anchors
# auto-generados por el extractor. Si cambia el extractor (nuevo modelo,
# prompt o versión de langextract), bumpear este valor permite auditar qué
# corrida los creó.
EXTRACTION_PIPELINE_VERSION_TAG = "v1"


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

            # Re-procesar invalida la evidencia AUTO previa pero respeta los
            # anchors MANUALES que dibujó el abogado. El abogado mantiene su
            # trabajo aunque cambie el extractor; un mismatch de sha tampoco
            # debe borrar lo que él/ella ancló a mano (queda visible y la UI
            # puede marcar "sha cambió" si fuera necesario).
            if id_extraccion and evidencia is not None:
                await session.execute(
                    text(
                        "DELETE FROM dt_extraccion_evidencia "
                        "WHERE id_extraccion = :id AND origen = 'auto'"
                    ),
                    {"id": id_extraccion},
                )
                if evidencia and sha256_documento:
                    # Migración 010 — cada evidencia generada por el extractor
                    # nace como anchor auto/propuesto. El abogado después la
                    # confirma o rechaza vía PATCH /anchors/{id}.
                    ins_ev = text(
                        """
                        INSERT INTO dt_extraccion_evidencia (
                            id_tenant, id_extraccion, id_archivo, campo, page,
                            char_start, char_end, snippet, sha256_documento, confianza,
                            fuente_texto, id_ocr, confianza_ocr, bboxes,
                            origen, estado, creado_por, fecha_actualizacion
                        )
                        VALUES (
                            :id_tenant, :id_extraccion, :id_archivo, :campo, :page,
                            :char_start, :char_end, :snippet, :sha, :confianza,
                            :fuente_texto, :id_ocr, :confianza_ocr,
                            CAST(:bboxes AS JSONB),
                            'auto', 'propuesto', :creado_por, NOW()
                        )
                        """
                    )
                    creado_por = f"extractor:{EXTRACTION_PIPELINE_VERSION_TAG}"
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
                            "creado_por": creado_por,
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

    # SQL base que reusan list_anchors / get_anchor / get_evidencia.
    # Mantiene join con OCR para que el frontend pueda enlazar al .md.
    _ANCHOR_SELECT_SQL = """
        SELECT e.id_evidencia, e.id_extraccion, e.id_archivo,
               e.campo, e.page, e.char_start, e.char_end,
               e.snippet, e.sha256_documento, e.confianza,
               e.fuente_texto, e.id_ocr, e.confianza_ocr, e.bboxes,
               e.origen, e.estado, e.creado_por,
               e.fecha AS fecha_creacion, e.fecha_actualizacion,
               op.id_ocr_documento, doc.modelo AS ocr_modelo,
               doc.gcs_uri AS ocr_md_uri,
               op.char_start AS ocr_pagina_char_start,
               op.char_end   AS ocr_pagina_char_end
        FROM dt_extraccion_evidencia e
        LEFT JOIN dt_ocr_pagina op  ON op.id_ocr_pagina    = e.id_ocr
        LEFT JOIN dt_ocr_documento doc ON doc.id_ocr_documento = op.id_ocr_documento
    """

    async def get_evidencia(self, id_extraccion: int) -> list[dict]:
        """Devuelve evidencia de una extracción con la procedencia (pdf_text/ocr)
        para que el frontend muestre el badge correcto en cada campo. Cuando
        la evidencia es OCR, también devuelve gcs_uri al .md para enlazar.

        Alias retrocompatible de `list_anchors()`. Se mantiene porque hay
        callers (frontend pre-010) que llaman a /extracciones/{id}/evidencia.
        """
        return await self.list_anchors(id_extraccion)

    async def list_anchors(
        self,
        id_extraccion: int,
        *,
        include_rejected: bool = True,
    ) -> list[dict]:
        """Anchors de una extracción (auto + manual). Por default incluye los
        rechazados — el frontend decide si los oculta. Cuando se llama desde
        el visor en modo "ver activos" pasar `include_rejected=False`.
        """
        if not self.engine:
            return []
        sql = self._ANCHOR_SELECT_SQL + " WHERE e.id_extraccion = :id_extraccion"
        if not include_rejected:
            sql += " AND e.estado != 'rechazado'"
        sql += " ORDER BY e.page NULLS LAST, e.char_start NULLS LAST, e.id_evidencia"
        async with self.session_factory() as session:
            res = await session.execute(text(sql), {"id_extraccion": id_extraccion})
            return [dict(r) for r in res.mappings().all()]

    async def get_anchor(self, id_anchor: int) -> dict | None:
        if not self.engine:
            return None
        sql = self._ANCHOR_SELECT_SQL + " WHERE e.id_evidencia = :id"
        async with self.session_factory() as session:
            res = await session.execute(text(sql), {"id": id_anchor})
            row = res.mappings().first()
            return dict(row) if row else None

    async def create_anchor(
        self,
        *,
        id_extraccion: int,
        campo: str,
        page: int | None,
        char_start: int | None,
        char_end: int | None,
        snippet: str | None,
        fuente_texto: str,
        bboxes: list[list[float]] | None,
        id_ocr: int | None,
        creado_por: str,
    ) -> dict:
        """Crea un anchor MANUAL ligado a una extracción existente.

        Carga el sha256 actual del archivo desde dt_archivos — el anchor
        queda atado al estado actual del documento. Si después se reprocesa
        el archivo con un PDF distinto, este anchor seguirá apuntando al
        sha viejo (la UI puede detectarlo comparando con `dt_archivos.sha256`
        y marcar "evidencia stale").

        Devuelve el row completo con id_anchor y campos derivados (join OCR).
        """
        import json
        if not self.engine:
            raise RuntimeError("DB no inicializada")
        async with self.session_factory() as session:
            ctx = await session.execute(
                text(
                    """
                    SELECT x.id_tenant, x.id_archivo, a.sha256
                    FROM dt_extraccion x
                    JOIN dt_archivos a ON a.id_archivo = x.id_archivo
                    WHERE x.id_extraccion = :id
                    """
                ),
                {"id": id_extraccion},
            )
            ctx_row = ctx.first()
            if not ctx_row:
                raise ValueError(f"Extracción {id_extraccion} no existe")
            id_tenant, id_archivo, sha256_doc = ctx_row

            ins = await session.execute(
                text(
                    """
                    INSERT INTO dt_extraccion_evidencia (
                        id_tenant, id_extraccion, id_archivo, campo, page,
                        char_start, char_end, snippet, sha256_documento,
                        fuente_texto, id_ocr, bboxes,
                        origen, estado, creado_por, fecha_actualizacion
                    )
                    VALUES (
                        :id_tenant, :id_extraccion, :id_archivo, :campo, :page,
                        :char_start, :char_end, :snippet, :sha,
                        :fuente_texto, :id_ocr, CAST(:bboxes AS JSONB),
                        'manual', 'confirmado', :creado_por, NOW()
                    )
                    RETURNING id_evidencia
                    """
                ),
                {
                    "id_tenant": id_tenant,
                    "id_extraccion": id_extraccion,
                    "id_archivo": id_archivo,
                    "campo": campo,
                    "page": page,
                    "char_start": char_start,
                    "char_end": char_end,
                    "snippet": (snippet or "")[:500] or None,
                    "sha": sha256_doc,
                    "fuente_texto": fuente_texto,
                    "id_ocr": id_ocr,
                    "bboxes": json.dumps(bboxes) if bboxes else None,
                    "creado_por": creado_por,
                },
            )
            id_anchor = ins.scalar_one()
            await session.commit()
        # Re-lee con join OCR para devolver el shape canónico.
        return await self.get_anchor(id_anchor) or {}

    async def update_anchor(
        self,
        id_anchor: int,
        *,
        campo: str | None = None,
        snippet: str | None = None,
        estado: str | None = None,
        page: int | None = None,
        char_start: int | None = None,
        char_end: int | None = None,
        bboxes: list[list[float]] | None = None,
        bboxes_set: bool = False,
    ) -> dict | None:
        """Patch parcial. Solo los campos provistos se modifican.

        `bboxes_set` distingue "no me lo pases" de "borralo a NULL" — para los
        otros campos los pasamos como None y los ignoramos en el COALESCE.
        Para bboxes necesitamos el flag porque NULL es un valor legítimo (caso:
        anchor cambió de OCR a pdf_text).
        """
        import json
        if not self.engine:
            return None
        sets: list[str] = []
        params: dict = {"id": id_anchor}
        if campo is not None:
            sets.append("campo = :campo")
            params["campo"] = campo
        if snippet is not None:
            sets.append("snippet = :snippet")
            params["snippet"] = snippet[:500] or None
        if estado is not None:
            if estado not in ("propuesto", "confirmado", "rechazado"):
                raise ValueError(f"estado inválido: {estado}")
            sets.append("estado = :estado")
            params["estado"] = estado
        if page is not None:
            sets.append("page = :page")
            params["page"] = page
        if char_start is not None:
            sets.append("char_start = :char_start")
            params["char_start"] = char_start
        if char_end is not None:
            sets.append("char_end = :char_end")
            params["char_end"] = char_end
        if bboxes_set:
            sets.append("bboxes = CAST(:bboxes AS JSONB)")
            params["bboxes"] = json.dumps(bboxes) if bboxes else None
        if not sets:
            return await self.get_anchor(id_anchor)
        sets.append("fecha_actualizacion = NOW()")
        sql = (
            f"UPDATE dt_extraccion_evidencia SET {', '.join(sets)} "
            f"WHERE id_evidencia = :id RETURNING id_evidencia"
        )
        async with self.session_factory() as session:
            res = await session.execute(text(sql), params)
            row = res.first()
            if not row:
                return None
            await session.commit()
        return await self.get_anchor(id_anchor)

    async def delete_anchor(self, id_anchor: int) -> str | None:
        """Borra o sof-borra un anchor.

        - Si origen='manual': DELETE físico — fue trabajo del usuario, él decide.
        - Si origen='auto': UPDATE estado='rechazado' — preservamos auditoría de
          qué propuso el extractor.

        Devuelve 'deleted' | 'rejected' | None (si no existe).
        """
        if not self.engine:
            return None
        async with self.session_factory() as session:
            res = await session.execute(
                text("SELECT origen FROM dt_extraccion_evidencia WHERE id_evidencia = :id"),
                {"id": id_anchor},
            )
            row = res.first()
            if not row:
                return None
            origen = row[0]
            if origen == "manual":
                await session.execute(
                    text("DELETE FROM dt_extraccion_evidencia WHERE id_evidencia = :id"),
                    {"id": id_anchor},
                )
                action = "deleted"
            else:
                await session.execute(
                    text(
                        "UPDATE dt_extraccion_evidencia "
                        "SET estado = 'rechazado', fecha_actualizacion = NOW() "
                        "WHERE id_evidencia = :id"
                    ),
                    {"id": id_anchor},
                )
                action = "rejected"
            await session.commit()
            return action

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
