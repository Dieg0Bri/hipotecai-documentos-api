"""
BaseExtractor — clase abstracta común para todos los extractores.

Cada subclase declara:
  · prompt(self) → str con instrucciones específicas
  · examples(self) → list[ExampleData] few-shot
  · parse(self, lx_result) → dict con los campos extraídos

El método `extract(text)` orquesta langextract.extract y devuelve
ExtractionResult.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

from src.core.config import settings
from src.models.schemas import ExtractionResult, TipoDocumento

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    tipo: TipoDocumento = "otro"

    @abstractmethod
    def prompt(self) -> str:
        ...

    @abstractmethod
    def examples(self) -> list[Any]:
        ...

    @abstractmethod
    def parse(self, lx_extractions: list[Any]) -> dict:
        ...

    # ───── Plumbing común ─────

    def extract(self, text: str) -> ExtractionResult:
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY ausente — extracción vacía.")
            return ExtractionResult(tipo=self.tipo, datos={}, confianza=0.0)

        try:
            import langextract as lx  # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError("langextract no instalado") from exc

        try:
            from langextract import data as lxdata  # type: ignore

            def _to_example(ex: dict):
                return lxdata.ExampleData(
                    text=ex["text"],
                    extractions=[
                        lxdata.Extraction(
                            extraction_class=e["extraction_class"],
                            extraction_text=e["extraction_text"],
                            attributes=e.get("attributes", {}),
                        )
                        for e in ex["extractions"]
                    ],
                )

            examples = [_to_example(ex) for ex in self.examples()]
        except ImportError:
            examples = self.examples()

        lx_result = lx.extract(
            text_or_documents=text[:80_000],
            prompt_description=self.prompt(),
            examples=examples,
            model_id=settings.GEMINI_MODEL_ID,
            api_key=settings.GEMINI_API_KEY,
            temperature=settings.LANGEXTRACT_TEMPERATURE,
        )

        extractions = list(getattr(lx_result, "extractions", []) or [])
        datos = self.parse(extractions)

        spans: list[dict] = []
        for ex in extractions:
            interval = getattr(ex, "char_interval", None)
            if interval:
                spans.append({
                    "field": getattr(ex, "extraction_class", None),
                    "value": getattr(ex, "extraction_text", None),
                    "start_char": getattr(interval, "start_pos", None),
                    "end_char": getattr(interval, "end_pos", None),
                })

        confianza = self._estimate_confidence(datos)
        return ExtractionResult(tipo=self.tipo, datos=datos, confianza=confianza, spans=spans)

    @staticmethod
    def _estimate_confidence(datos: dict) -> float:
        """Confianza basada en proporción de campos no nulos."""
        if not datos:
            return 0.0
        non_null = sum(1 for v in datos.values() if v not in (None, "", [], {}))
        return round(min(0.99, non_null / max(1, len(datos))), 3)


# Helper: resolver extractor por tipo
def get_extractor(tipo: TipoDocumento) -> "BaseExtractor":
    from src.extractors.escritura import EscrituraExtractor
    from src.extractors.cert_dominio_vigente import CertDominioVigenteExtractor
    from src.extractors.cert_hipotecas_gravamenes import CertHipotecasExtractor
    from src.extractors.cert_avaluo_sii import CertAvaluoSiiExtractor
    from src.extractors.cert_municipal import CertMunicipalExtractor
    from src.extractors.plano_propiedad import PlanoPropiedadExtractor
    from src.extractors.plan_regulador import PlanReguladorExtractor

    mapping: dict[TipoDocumento, type[BaseExtractor]] = {
        "escritura": EscrituraExtractor,
        "cert_dominio_vigente": CertDominioVigenteExtractor,
        "cert_hipotecas_gravamenes": CertHipotecasExtractor,
        "cert_avaluo_sii": CertAvaluoSiiExtractor,
        "cert_municipal": CertMunicipalExtractor,
        "plano_propiedad": PlanoPropiedadExtractor,
        "plan_regulador": PlanReguladorExtractor,
    }
    cls = mapping.get(tipo)
    if not cls:
        raise ValueError(f"No hay extractor para tipo='{tipo}'")
    return cls()
