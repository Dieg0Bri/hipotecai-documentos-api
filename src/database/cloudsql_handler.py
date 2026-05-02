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

    async def save_extraction(self, *, id_archivo: int, tipo: str, datos: dict, confianza: float, spans: list):
        sql = text(
            """
            INSERT INTO dt_extraccion (id_archivo, schema_codigo, datos, spans, confianza, fecha)
            VALUES (:id_archivo, :schema, CAST(:datos AS JSONB), CAST(:spans AS JSONB), :confianza, NOW())
            ON CONFLICT (id_archivo, schema_codigo) DO UPDATE SET
                datos = EXCLUDED.datos,
                spans = EXCLUDED.spans,
                confianza = EXCLUDED.confianza,
                fecha = NOW()
            RETURNING id_extraccion
            """
        )
        import json
        async with self.session_factory() as session:
            result = await session.execute(sql, {
                "id_archivo": id_archivo,
                "schema": tipo,
                "datos": json.dumps(datos),
                "spans": json.dumps(spans),
                "confianza": confianza,
            })
            await session.execute(
                text("UPDATE dt_archivos SET estado_procesamiento = 'procesado', fecha_actualizacion = NOW() WHERE id_archivo = :id"),
                {"id": id_archivo},
            )
            await session.commit()
            row = result.first()
            return row[0] if row else None

    async def close(self):
        if self.engine:
            await self.engine.dispose()
