"""
Schemas Pydantic — uno por cada tipo de documento legal chileno.
Las extracciones devuelven un objeto con campos tipados + `_spans`
con los fragmentos del texto fuente que justifican cada valor.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TipoDocumento = Literal[
    "escritura",
    "cert_dominio_vigente",
    "cert_hipotecas_gravamenes",
    "cert_avaluo_sii",
    "cert_municipal",
    "plano_propiedad",
    "plan_regulador",
    "otro",
]


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoDocumento
    texto: str = Field(..., min_length=10)
    folio: str | None = None
    id_archivo: int | None = None


class ExtractFromGCSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoDocumento
    folio: str
    gcs_path: str
    id_archivo: int | None = None


# ─────────── Schemas por tipo de documento ───────────

class EscrituraExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    tipo_acto: str | None = Field(None, description="Compraventa, hipoteca, alzamiento, herencia…")
    fecha_otorgamiento: str | None = None
    notario_nombre: str | None = None
    notaria_numero: str | None = None
    repertorio: str | None = None
    foja: str | None = None
    rol_propiedad: str | None = None
    direccion_propiedad: str | None = None
    superficie_m2: float | None = None
    deslindes: dict | None = None
    vendedores: list[str] = []
    compradores: list[str] = []
    precio_clp: int | None = None
    precio_uf: float | None = None
    forma_pago: str | None = None


class CertDominioVigenteExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    cbr_emisor: str | None = None
    fecha_emision: str | None = None
    foja: str | None = None
    numero_inscripcion: str | None = None
    anio_inscripcion: int | None = None
    titular_actual: str | None = None
    titular_rut: str | None = None
    rol_propiedad: str | None = None
    direccion: str | None = None
    superficie_m2: float | None = None


class CertHipotecasExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    cbr_emisor: str | None = None
    fecha_emision: str | None = None
    foja: str | None = None
    hipotecas_vigentes: list[dict] = []
    prohibiciones: list[str] = []
    gravamenes: list[str] = []
    interdicciones: list[str] = []
    libre_de_gravamenes: bool | None = None


class CertAvaluoSiiExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    rol_avaluo: str | None = None
    comuna: str | None = None
    fecha_emision: str | None = None
    avaluo_total_clp: int | None = None
    avaluo_terreno_clp: int | None = None
    avaluo_construccion_clp: int | None = None
    superficie_terreno_m2: float | None = None
    superficie_construida_m2: float | None = None
    destino: str | None = None
    exento_iva: bool | None = None


class CertMunicipalExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    municipalidad: str | None = None
    fecha_emision: str | None = None
    numero_municipal: str | None = None
    direccion_oficial: str | None = None
    no_expropiacion: bool | None = None
    recepcion_final: dict | None = None
    permiso_edificacion: dict | None = None


class PlanoPropiedadExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    tipo_plano: str | None = None
    superficie_total_m2: float | None = None
    superficie_construida_m2: float | None = None
    deslindes: dict | None = None
    profesional: str | None = None
    fecha_plano: str | None = None


class PlanReguladorExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    comuna: str | None = None
    zonificacion: str | None = None
    usos_permitidos: list[str] = []
    altura_maxima: str | None = None
    coef_constructibilidad: float | None = None
    coef_ocupacion_suelo: float | None = None
    densidad_max: str | None = None


class ExtractionResult(BaseModel):
    """Wrapper común que devuelven los endpoints."""
    model_config = ConfigDict(extra="allow")

    tipo: TipoDocumento
    datos: dict
    confianza: float = 0.0
    spans: list[dict] = []
    schema_version: str = "v0"
