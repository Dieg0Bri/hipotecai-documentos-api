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

            # Migración 011 — anchors viven inline en dt_extraccion.anchors
            # como un JSONB array. El reproceso del extractor:
            #   - Borra los anchors AUTO previos (origen='auto')
            #   - Agrega los nuevos como propuestos
            #   - Conserva los MANUAL que el abogado haya creado
            if id_extraccion and evidencia is not None:
                await self._merge_auto_anchors_into_blob(
                    session=session,
                    id_extraccion=id_extraccion,
                    nuevos_auto=evidencia or [],
                    sha256_documento=sha256_documento,
                )

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

    # ─────────────────── Anchors (migración 011) ───────────────────
    # Los anchors viven como JSONB array en dt_extraccion.anchors. Esta
    # sección es CRUD sobre ese blob. Cada anchor tiene un id UUID v4
    # generado al crear (string, no int). El reproceso del extractor
    # reemplaza los origen='auto' y conserva los origen='manual'.
    #
    # Schema del blob (ver migración 011):
    #   { "version": 1, "anchors": [ {id, campo, page, ...}, ... ] }
    #
    # Trade-off: cada mutación lee el blob, lo modifica, lo escribe.
    # Race condition entre dos usuarios editando el mismo doc: último
    # gana (sin optimistic locking en v0). Aceptable para hipotecai
    # porque normalmente solo un abogado revisa un expediente a la vez.

    @staticmethod
    def _empty_blob() -> dict:
        return {"version": 1, "anchors": []}

    @staticmethod
    def _enrich_anchor_with_ocr(anchor: dict, ocr_map: dict[int, dict]) -> dict:
        """Agrega metadata del OCR (modelo, gcs_uri, offsets de pagina) cuando
        el anchor tiene id_ocr. La metadata se reusa para que el frontend
        pueda linkar al markdown OCR sin re-fetcharlo.
        """
        out = dict(anchor)
        id_ocr = anchor.get("id_ocr")
        if id_ocr and id_ocr in ocr_map:
            m = ocr_map[id_ocr]
            out["id_ocr_documento"] = m.get("id_ocr_documento")
            out["ocr_modelo"] = m.get("modelo")
            out["ocr_md_uri"] = m.get("gcs_uri")
            out["ocr_pagina_char_start"] = m.get("char_start")
            out["ocr_pagina_char_end"] = m.get("char_end")
        else:
            out["id_ocr_documento"] = None
            out["ocr_modelo"] = None
            out["ocr_md_uri"] = None
            out["ocr_pagina_char_start"] = None
            out["ocr_pagina_char_end"] = None
        return out

    async def _fetch_ocr_map_for_extraction(
        self, session, id_extraccion: int,
    ) -> dict[int, dict]:
        """Trae el join de dt_ocr_pagina + dt_ocr_documento para los id_ocr
        referenciados desde los anchors de UNA extracción. Una sola query.
        """
        res = await session.execute(
            text(
                """
                SELECT op.id_ocr_pagina, op.id_ocr_documento, op.char_start, op.char_end,
                       doc.modelo, doc.gcs_uri
                FROM dt_ocr_pagina op
                JOIN dt_ocr_documento doc ON doc.id_ocr_documento = op.id_ocr_documento
                WHERE op.id_ocr_documento IN (
                    SELECT DISTINCT doc2.id_ocr_documento
                    FROM dt_extraccion x
                    JOIN dt_ocr_documento doc2 ON doc2.id_archivo = x.id_archivo
                    WHERE x.id_extraccion = :id
                )
                """
            ),
            {"id": id_extraccion},
        )
        return {r["id_ocr_pagina"]: dict(r) for r in res.mappings().all()}

    async def _load_blob(self, session, id_extraccion: int) -> tuple[dict, int, int] | None:
        """Lee el blob de una extracción. Devuelve (blob, id_archivo, id_tenant).
        Devuelve None si la extracción no existe."""
        res = await session.execute(
            text(
                """
                SELECT x.anchors, x.id_archivo, x.id_tenant
                FROM dt_extraccion x WHERE x.id_extraccion = :id
                """
            ),
            {"id": id_extraccion},
        )
        row = res.mappings().first()
        if not row:
            return None
        blob = row["anchors"] or self._empty_blob()
        return blob, row["id_archivo"], row["id_tenant"]

    async def _save_blob(self, session, id_extraccion: int, blob: dict) -> None:
        import json
        await session.execute(
            text("UPDATE dt_extraccion SET anchors = CAST(:b AS JSONB) WHERE id_extraccion = :id"),
            {"id": id_extraccion, "b": json.dumps(blob, ensure_ascii=False)},
        )

    async def _find_anchor_extraction(self, session, id_anchor: str) -> int | None:
        """Busca a qué id_extraccion pertenece un anchor por su UUID. Usa el
        GIN index sobre anchors para evitar full scan."""
        res = await session.execute(
            text(
                """
                SELECT id_extraccion FROM dt_extraccion
                WHERE anchors @> jsonb_build_object(
                    'anchors', jsonb_build_array(jsonb_build_object('id', :id))
                )
                LIMIT 1
                """
            ),
            {"id": id_anchor},
        )
        row = res.first()
        return row[0] if row else None

    async def _merge_auto_anchors_into_blob(
        self,
        *,
        session,
        id_extraccion: int,
        nuevos_auto: list[dict],
        sha256_documento: str | None,
    ) -> None:
        """Llamado desde save_extraction: borra los anchors origen='auto'
        del blob actual y agrega los nuevos como propuestos. Conserva los
        origen='manual'."""
        from datetime import datetime, timezone
        from uuid import uuid4
        loaded = await self._load_blob(session, id_extraccion)
        if loaded is None:
            return
        blob, _id_archivo, _id_tenant = loaded
        manual = [a for a in blob.get("anchors", []) if a.get("origen") == "manual"]
        now = datetime.now(timezone.utc).isoformat()
        creado_por = f"extractor:{EXTRACTION_PIPELINE_VERSION_TAG}"
        added: list[dict] = []
        for ev in nuevos_auto:
            added.append({
                "id": str(uuid4()),
                "campo": ev.get("campo"),
                "page": ev.get("page"),
                "char_start": ev.get("char_start"),
                "char_end": ev.get("char_end"),
                "snippet": (ev.get("snippet") or "")[:500] or None,
                "fuente_texto": ev.get("fuente_texto", "pdf_text"),
                "bboxes": ev.get("bboxes"),
                "id_ocr": ev.get("id_ocr"),
                "confianza_ocr": ev.get("confianza_ocr"),
                "confianza": ev.get("confianza"),
                "sha256_documento": sha256_documento,
                "origen": "auto",
                "estado": "propuesto",
                "creado_por": creado_por,
                "created_at": now,
                "updated_at": now,
            })
        blob["anchors"] = manual + added
        await self._save_blob(session, id_extraccion, blob)

    @staticmethod
    def _sort_key(a: dict) -> tuple:
        # NULLs al final para emular el ORDER BY page NULLS LAST, char_start NULLS LAST.
        page = a.get("page")
        cs = a.get("char_start")
        return (page is None, page or 0, cs is None, cs or 0, a.get("id") or "")

    async def get_evidencia(self, id_extraccion: int) -> list[dict]:
        """Alias retrocompatible de `list_anchors()`."""
        return await self.list_anchors(id_extraccion)

    async def list_anchors(
        self, id_extraccion: int, *, include_rejected: bool = True,  # noqa: ARG002
    ) -> list[dict]:
        """Anchors de una extracción ordenados por (page, char_start, id).

        El parámetro `include_rejected` se mantiene en la firma para no
        romper callers, pero a partir de 011 NO existen rechazados — el
        rechazo es hard delete. Siempre devolvemos todos los anchors del
        blob.
        """
        if not self.engine:
            return []
        async with self.session_factory() as session:
            loaded = await self._load_blob(session, id_extraccion)
            if loaded is None:
                return []
            blob, id_archivo, _id_tenant = loaded
            anchors = blob.get("anchors", [])
            ocr_map = await self._fetch_ocr_map_for_extraction(session, id_extraccion)
            out: list[dict] = []
            for a in sorted(anchors, key=self._sort_key):
                enriched = self._enrich_anchor_with_ocr(a, ocr_map)
                # Conservar nombres legacy que el frontend ya consume.
                enriched["id_evidencia"] = enriched["id"]  # alias para compat
                enriched["id_extraccion"] = id_extraccion
                enriched["id_archivo"] = id_archivo
                # Campos derivados que antes venían de columnas SQL:
                enriched["fecha_creacion"] = enriched.get("created_at")
                enriched["fecha_actualizacion"] = enriched.get("updated_at")
                out.append(enriched)
            return out

    async def get_anchor(self, id_anchor: str) -> dict | None:
        if not self.engine:
            return None
        async with self.session_factory() as session:
            id_extraccion = await self._find_anchor_extraction(session, id_anchor)
            if id_extraccion is None:
                return None
        items = await self.list_anchors(id_extraccion)
        for it in items:
            if it.get("id") == id_anchor:
                return it
        return None

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
        """Crea un anchor MANUAL: agrega un elemento al array del blob.

        Carga el sha256 actual del archivo para tag-earlo en el anchor —
        si después se reprocesa con un PDF distinto, las coords pueden
        quedar stale y la UI puede detectarlo comparando.
        """
        from datetime import datetime, timezone
        from uuid import uuid4
        if not self.engine:
            raise RuntimeError("DB no inicializada")
        async with self.session_factory() as session:
            ctx = await session.execute(
                text(
                    """
                    SELECT a.sha256 FROM dt_extraccion x
                    JOIN dt_archivos a ON a.id_archivo = x.id_archivo
                    WHERE x.id_extraccion = :id
                    """
                ),
                {"id": id_extraccion},
            )
            ctx_row = ctx.first()
            if not ctx_row:
                raise ValueError(f"Extracción {id_extraccion} no existe")
            sha256_doc = ctx_row[0]
            loaded = await self._load_blob(session, id_extraccion)
            if loaded is None:
                raise ValueError(f"Extracción {id_extraccion} no existe")
            blob, _id_archivo, _id_tenant = loaded
            now = datetime.now(timezone.utc).isoformat()
            new_id = str(uuid4())
            blob.setdefault("anchors", []).append({
                "id": new_id,
                "campo": campo,
                "page": page,
                "char_start": char_start,
                "char_end": char_end,
                "snippet": (snippet or "")[:500] or None,
                "fuente_texto": fuente_texto,
                "bboxes": bboxes,
                "id_ocr": id_ocr,
                "confianza_ocr": None,
                "confianza": None,
                "sha256_documento": sha256_doc,
                "origen": "manual",
                "estado": "confirmado",  # manual nace confirmado
                "creado_por": creado_por,
                "created_at": now,
                "updated_at": now,
            })
            await self._save_blob(session, id_extraccion, blob)
            await session.commit()
        result = await self.get_anchor(new_id)
        return result or {}

    async def update_anchor(
        self,
        id_anchor: str,
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
        """Patch parcial sobre un anchor del blob. Solo los campos provistos
        se modifican; el resto permanece intacto.

        `estado='rechazado'` se permite por compat con el cliente actual,
        pero en el modelo 011 ya no existe — el frontend debería llamar a
        DELETE en su lugar. Si llega 'rechazado', lo tratamos como delete.
        """
        from datetime import datetime, timezone
        if not self.engine:
            return None
        if estado is not None and estado not in ("propuesto", "confirmado", "rechazado"):
            raise ValueError(f"estado inválido: {estado}")
        # Rechazado se interpreta como delete (consistencia con el nuevo modelo).
        if estado == "rechazado":
            await self.delete_anchor(id_anchor)
            return None
        async with self.session_factory() as session:
            id_extraccion = await self._find_anchor_extraction(session, id_anchor)
            if id_extraccion is None:
                return None
            loaded = await self._load_blob(session, id_extraccion)
            if loaded is None:
                return None
            blob, _id_archivo, _id_tenant = loaded
            now = datetime.now(timezone.utc).isoformat()
            patched_one = False
            for a in blob.get("anchors", []):
                if a.get("id") != id_anchor:
                    continue
                if campo is not None: a["campo"] = campo
                if snippet is not None: a["snippet"] = snippet[:500] or None
                if estado is not None: a["estado"] = estado
                if page is not None: a["page"] = page
                if char_start is not None: a["char_start"] = char_start
                if char_end is not None: a["char_end"] = char_end
                if bboxes_set: a["bboxes"] = bboxes
                a["updated_at"] = now
                patched_one = True
                break
            if not patched_one:
                return None
            await self._save_blob(session, id_extraccion, blob)
            await session.commit()
        return await self.get_anchor(id_anchor)

    async def delete_anchor(self, id_anchor: str) -> str | None:
        """Hard delete: remueve el anchor del array del blob.

        En el modelo 011 no hay soft-delete — auto o manual, ambos se
        borran físicamente. Si el extractor vuelve a proponerlo en un
        reproceso, reaparecerá con un nuevo UUID.

        Devuelve 'deleted' si lo encontró, None si no.
        """
        if not self.engine:
            return None
        async with self.session_factory() as session:
            id_extraccion = await self._find_anchor_extraction(session, id_anchor)
            if id_extraccion is None:
                return None
            loaded = await self._load_blob(session, id_extraccion)
            if loaded is None:
                return None
            blob, _id_archivo, _id_tenant = loaded
            before = len(blob.get("anchors", []))
            blob["anchors"] = [a for a in blob.get("anchors", []) if a.get("id") != id_anchor]
            if len(blob["anchors"]) == before:
                return None
            await self._save_blob(session, id_extraccion, blob)
            await session.commit()
            return "deleted"

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
