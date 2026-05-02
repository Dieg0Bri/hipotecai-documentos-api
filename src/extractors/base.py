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
        # Vertex AI con ADC (Application Default Credentials del SA del Cloud Run)
        # es el modo preferido. Si VERTEX_AI=false cae al modo Generative Language API
        # con GEMINI_API_KEY (obsoleto, solo para entornos sin GCP).
        use_vertex = settings.VERTEX_AI and settings.GOOGLE_CLOUD_PROJECT
        if not use_vertex and not settings.GEMINI_API_KEY:
            logger.warning("Sin VERTEX_AI ni GEMINI_API_KEY — extracción vacía.")
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

        # language_model_params se pasa al constructor de GeminiLanguageModel.
        # Si vertexai=True, langextract usa google.genai con ADC sin API key.
        if use_vertex:
            lm_params = {
                "vertexai": True,
                "project": settings.GOOGLE_CLOUD_PROJECT,
                "location": settings.VERTEX_LOCATION,
            }
            extract_kwargs = {"language_model_params": lm_params}
        else:
            extract_kwargs = {"api_key": settings.GEMINI_API_KEY}

        lx_result = lx.extract(
            text_or_documents=text[:80_000],
            prompt_description=self.prompt(),
            examples=examples,
            model_id=settings.GEMINI_MODEL_ID,
            temperature=settings.LANGEXTRACT_TEMPERATURE,
            **extract_kwargs,
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
    # Imports diferidos para evitar ciclos.
    from src.extractors.escritura import (
        EscrituraExtractor, EscrituraCompraventaExtractor, EscrituraAnteriorExtractor,
    )
    from src.extractors.cert_dominio_vigente import CertDominioVigenteExtractor
    from src.extractors.cert_hipotecas_gravamenes import CertHipotecasExtractor
    from src.extractors.cert_avaluo_sii import CertAvaluoSiiExtractor
    from src.extractors.cert_municipal import CertMunicipalExtractor
    from src.extractors.plano_propiedad import PlanoPropiedadExtractor
    from src.extractors.plan_regulador import PlanReguladorExtractor
    from src.extractors.carnet_identidad import CarnetIdentidadExtractor
    from src.extractors.cert_estado_civil import (
        CertMatrimonioExtractor, CertUnionCivilExtractor,
        CertSolteriaExtractor, CertDefuncionExtractor, DeclJuradaSolteriaExtractor,
    )
    from src.extractors.cert_deuda_contribuciones import CertDeudaContribucionesExtractor
    from src.extractors.certs_dom import (
        CertNoExpropiacionDomExtractor, CertNoExpropiacionServiuExtractor,
        CertNumeroDomExtractor, CertRecepcionFinalDomExtractor,
    )
    from src.extractors.condicionales import (
        ERutSiiExtractor, EscrituraConstitucionSocialExtractor, CertVigenciaPoderesExtractor,
        CertDeudaGastosComunesExtractor, ActaAsambleaCopropietariosExtractor,
        ResolucionServiuExtractor,
        SentenciaJudicialExtractor, CertEjecutoriaExtractor,
        CertSubdivisionSagExtractor, PlanoSubdivisionSagExtractor, CertConadiExtractor,
        CertPosesionEfectivaExtractor, CertExencionHerenciaSiiExtractor,
        EscrituraAlzamientoHipotecaExtractor, EscrituraBienFamiliarExtractor,
        EscrituraRenunciaUsufructoExtractor,
    )

    mapping: dict[str, type[BaseExtractor]] = {
        # CBR
        "cert_dominio_vigente": CertDominioVigenteExtractor,
        "cert_hipotecas_gravamenes": CertHipotecasExtractor,
        # Escrituras
        "escritura": EscrituraExtractor,
        "escritura_compraventa": EscrituraCompraventaExtractor,
        "escritura_anterior": EscrituraAnteriorExtractor,
        "escritura_alzamiento_hipoteca": EscrituraAlzamientoHipotecaExtractor,
        "escritura_bien_familiar": EscrituraBienFamiliarExtractor,
        "escritura_renuncia_usufructo": EscrituraRenunciaUsufructoExtractor,
        # Tributario
        "cert_avaluo_sii": CertAvaluoSiiExtractor,
        "cert_deuda_contribuciones": CertDeudaContribucionesExtractor,
        # Identidad
        "carnet_identidad": CarnetIdentidadExtractor,
        # Estado civil
        "cert_matrimonio": CertMatrimonioExtractor,
        "cert_union_civil": CertUnionCivilExtractor,
        "cert_solteria": CertSolteriaExtractor,
        "cert_defuncion": CertDefuncionExtractor,
        "decl_jurada_solteria": DeclJuradaSolteriaExtractor,
        # DOM / SERVIU
        "cert_no_expropiacion_dom": CertNoExpropiacionDomExtractor,
        "cert_no_expropiacion_serviu": CertNoExpropiacionServiuExtractor,
        "cert_numero_dom": CertNumeroDomExtractor,
        "cert_recepcion_final_dom": CertRecepcionFinalDomExtractor,
        "cert_municipal": CertMunicipalExtractor,  # legacy genérico
        # Persona jurídica
        "e_rut_sii": ERutSiiExtractor,
        "escritura_constitucion_social": EscrituraConstitucionSocialExtractor,
        "cert_vigencia_poderes": CertVigenciaPoderesExtractor,
        # Condominio
        "cert_deuda_gastos_comunes": CertDeudaGastosComunesExtractor,
        "acta_asamblea_copropietarios": ActaAsambleaCopropietariosExtractor,
        # SERVIU subsidio
        "resolucion_serviu": ResolucionServiuExtractor,
        # Tribunales
        "sentencia_judicial": SentenciaJudicialExtractor,
        "cert_ejecutoria": CertEjecutoriaExtractor,
        # Rural
        "cert_subdivision_sag": CertSubdivisionSagExtractor,
        "plano_subdivision_sag": PlanoSubdivisionSagExtractor,
        # Indígena
        "cert_conadi": CertConadiExtractor,
        # Herencia
        "cert_posesion_efectiva": CertPosesionEfectivaExtractor,
        "cert_exencion_herencia_sii": CertExencionHerenciaSiiExtractor,
        # Planos
        "plano_propiedad": PlanoPropiedadExtractor,
        "plan_regulador": PlanReguladorExtractor,
    }
    cls = mapping.get(tipo)
    if not cls:
        raise ValueError(f"No hay extractor para tipo='{tipo}'")
    return cls()
