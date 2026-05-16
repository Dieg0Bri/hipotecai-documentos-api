"""
Schemas Pydantic — uno por cada tipo de documento legal chileno.
Las extracciones devuelven un objeto con campos tipados + `_spans`
con los fragmentos del texto fuente que justifican cada valor.

Los campos de cada schema reflejan EXACTAMENTE los del formulario que
el abogado pidió rellenar (Doc "Formulario estudio de titulos").
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.catalogo import CODIGOS_VALIDOS


# El tipo se valida contra el catálogo en runtime; no usamos Literal[…]
# para no duplicar la lista en dos lugares.
TipoDocumento = str


def _validar_tipo(value: str) -> str:
    if value not in CODIGOS_VALIDOS:
        raise ValueError(f"tipo='{value}' no está en CODIGOS_VALIDOS")
    return value


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoDocumento
    texto: str = Field(..., min_length=10)
    folio: str | None = None
    id_archivo: int | None = None

    @field_validator("tipo")
    @classmethod
    def _v_tipo(cls, v: str) -> str:
        return _validar_tipo(v)


class ExtractFromGCSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoDocumento
    folio: str
    gcs_path: str
    id_archivo: int | None = None

    @field_validator("tipo")
    @classmethod
    def _v_tipo(cls, v: str) -> str:
        return _validar_tipo(v)


# ─────────── Schemas por tipo de documento ───────────

# ── Identidad ──────────────────────────────────────────────────────────────

class CarnetIdentidadExtraction(BaseModel):
    """Doc 3 §1 - Carnet de Identidad del Vendedor."""
    model_config = ConfigDict(extra="allow")
    rut: str | None = None
    rut_valido: bool | None = None  # validación algorítmica del DV
    nombre_completo: str | None = None
    nacionalidad: str | None = None
    profesion_oficio: str | None = None
    estado_civil_declarado: Literal[
        "soltero", "casado", "viudo", "divorciado", "conviviente_civil"
    ] | None = None
    fecha_nacimiento: str | None = None  # ISO YYYY-MM-DD


# ── Estado Civil ───────────────────────────────────────────────────────────

class CertEstadoCivilExtraction(BaseModel):
    """Doc 3 §2 - Cert. Registro Civil (matrimonio/unión civil/viudez/soltería).

    Comparte schema entre los 4 — el campo `tipo_cert` indica cuál.
    """
    model_config = ConfigDict(extra="allow")
    tipo_cert: Literal["matrimonio", "union_civil", "soltería", "viudez", "defuncion"] | None = None
    parte_a_nombre: str | None = None
    parte_a_rut: str | None = None
    parte_b_nombre: str | None = None
    parte_b_rut: str | None = None
    fecha_celebracion: str | None = None
    regimen: Literal[
        "sociedad_conyugal", "separacion_total_de_bienes", "participacion_gananciales", "no_aplica"
    ] | None = None
    subinscripcion: Literal[
        "separacion_total_de_bienes", "participacion_gananciales", "divorcio", "sin_subinscripcion"
    ] | None = None
    fecha_subinscripcion: str | None = None
    fecha_defuncion: str | None = None  # solo cert_defuncion / viudez


class DeclJuradaSolteriaExtraction(BaseModel):
    """Declaración personal simple, no notarial. La IA debe DETECTAR si tiene firma manuscrita."""
    model_config = ConfigDict(extra="allow")
    declarante_nombre: str | None = None
    declarante_rut: str | None = None
    fecha_declaracion: str | None = None
    tiene_firma_manuscrita: bool | None = None


# ── CBR ────────────────────────────────────────────────────────────────────

class CertDominioVigenteExtraction(BaseModel):
    """Doc 3 §3 - Cert. Dominio Vigente (CBR)."""
    model_config = ConfigDict(extra="allow")
    cbr_emisor: str | None = None
    fecha_emision: str | None = None
    foja: str | None = None
    numero_inscripcion: str | None = None
    anio_inscripcion: int | None = None
    propietarios: list[dict] = Field(
        default_factory=list,
        description="[{nombre, rut}] — la propiedad puede tener múltiples titulares",
    )
    rol_propiedad: str | None = None
    direccion: str | None = None
    superficie_m2: float | None = None

    # Cita del título anterior (eslabón previo de la cadena)
    cita_titulo_anterior: dict | None = None  # {foja, numero, anio, cbr}


class CertHipotecasExtraction(BaseModel):
    """Doc 3 §4 - Cert. Hipotecas y Gravámenes (GP).

    Spec del abogado: clasificación en TIERS:
      - tier_1: embargos, precautorias, litigios, bien familiar (BLOQUEO)
      - tier_2: hipotecas/prohibiciones de bancos (subsanable)
      - tier_3: limpio
    """
    model_config = ConfigDict(extra="allow")
    cbr_emisor: str | None = None
    fecha_emision: str | None = None
    foja: str | None = None
    numero_inscripcion: str | None = None
    anio_inscripcion: int | None = None
    rut_dueno: str | None = None

    hipotecas_vigentes: list[dict] = Field(
        default_factory=list,
        description="[{acreedor, fecha, foja, numero}]",
    )
    prohibiciones: list[str] = Field(default_factory=list)
    embargos: list[str] = Field(default_factory=list)
    interdicciones: list[str] = Field(default_factory=list)
    bien_familiar: bool | None = None

    tier_clasificacion: Literal["tier_1", "tier_2", "tier_3"] | None = None
    libre_de_gravamenes: bool | None = None


# ── Escrituras ─────────────────────────────────────────────────────────────

class EscrituraExtraction(BaseModel):
    """Schema genérico de escrituras públicas (compraventa, anterior, alzamiento, etc.)."""
    model_config = ConfigDict(extra="allow")
    tipo_acto: str | None = Field(None, description="Compraventa, hipoteca, alzamiento, donación…")
    fecha_otorgamiento: str | None = None
    notario_nombre: str | None = None
    notaria_numero: str | None = None
    repertorio: str | None = None

    # Tracto (Doc 3 §7 — escrituras anteriores requieren foja/numero/anio)
    foja: str | None = None
    numero_inscripcion: str | None = None
    anio_inscripcion: int | None = None
    cbr_inscripcion: str | None = None

    # Partes
    vendedor_nombre: str | None = None
    vendedor_rut: str | None = None
    vendedor_estado_civil: Literal["casado", "soltero", "viudo", "divorciado", "conviviente_civil"] | None = None
    vendedor_sociedad_conyugal_art150: bool | None = None  # patrimonio reservado

    comprador_nombre: str | None = None
    comprador_rut: str | None = None

    # Inmueble
    rol_propiedad: str | None = None
    direccion_propiedad: str | None = None
    superficie_m2: float | None = None
    deslindes: dict | None = None  # {norte, sur, oriente, poniente}

    # Económico
    precio_clp: int | None = None
    precio_uf: float | None = None
    forma_pago: str | None = None


class EscrituraAlzamientoExtraction(BaseModel):
    """Escritura donde un banco alza/cancela una hipoteca."""
    model_config = ConfigDict(extra="allow")
    fecha_otorgamiento: str | None = None
    notario_nombre: str | None = None
    notaria_numero: str | None = None
    institucion_acreedor: str | None = None  # razón social del banco
    institucion_rut: str | None = None
    hipoteca_alzada: dict | None = None  # {foja, numero, anio, fecha_inscripcion}
    representantes_banco: list[dict] = Field(
        default_factory=list,
        description="[{nombre, rut, fecha_personeria, notaria_personeria, fojas_personeria}]",
    )


class EscrituraBienFamiliarExtraction(BaseModel):
    """Autorización del cónyuge no propietario o desafectación de bien familiar."""
    model_config = ConfigDict(extra="allow")
    tipo_documento: Literal[
        "escritura_desafectacion", "autorizacion_conyuge", "sentencia_judicial"
    ] | None = None
    notaria_o_tribunal: str | None = None
    fecha_documento: str | None = None
    conyuge_nombre: str | None = None
    conyuge_rut: str | None = None
    consta_subinscripcion_cbr: bool | None = None


class EscrituraRenunciaUsufructoExtraction(BaseModel):
    """Renuncia o alzamiento de usufructo (también vale cert. defunción del usufructuario)."""
    model_config = ConfigDict(extra="allow")
    tipo_comprobante: Literal["renuncia", "defuncion"] | None = None
    fecha_documento: str | None = None
    usufructuario_nombre: str | None = None
    usufructuario_rut: str | None = None
    usufructo_cancelado_cbr: bool | None = None


# ── Tributario ─────────────────────────────────────────────────────────────

class CertAvaluoSiiExtraction(BaseModel):
    """Doc 3 §8 - Cert. Avalúo Fiscal (SII)."""
    model_config = ConfigDict(extra="allow")
    rol_avaluo: str | None = None  # formato XXXX-YY
    comuna: str | None = None
    fecha_emision: str | None = None
    avaluo_total_clp: int | None = None
    avaluo_terreno_clp: int | None = None
    avaluo_construccion_clp: int | None = None
    superficie_terreno_m2: float | None = None
    superficie_construida_m2: float | None = None
    destino: str | None = None  # habitacional, agrícola, comercial, …
    condicion: Literal["exento", "afecto"] | None = None
    semestre: str | None = None  # ej. "2026-1"


class CertDeudaContribucionesExtraction(BaseModel):
    """Doc 3 §9 - Cert. Deuda de Contribuciones (TGR)."""
    model_config = ConfigDict(extra="allow")
    rol_propiedad: str | None = None
    comuna: str | None = None
    fecha_emision: str | None = None
    estado_deuda: Literal["no_registra_deuda", "registra_deuda"] | None = None
    monto_total_moroso_clp: int | None = None
    cuotas_pendientes: int | None = None


# ── Urbanismo ──────────────────────────────────────────────────────────────

class CertNoExpropiacionExtraction(BaseModel):
    """Doc 3 §10 - Cert. No Expropiación (DOM o SERVIU)."""
    model_config = ConfigDict(extra="allow")
    emisor: Literal["dom", "serviu"] | None = None
    municipalidad: str | None = None
    fecha_emision: str | None = None
    rol_propiedad: str | None = None
    direccion: str | None = None
    estado_afectacion: Literal["afecta", "no_afecta"] | None = None
    motivo_afectacion: str | None = None  # ensanche, área verde, vialidad…


class CertNumeroDomExtraction(BaseModel):
    """Doc 3 §10 - Cert. de Número (DOM)."""
    model_config = ConfigDict(extra="allow")
    municipalidad: str | None = None
    fecha_emision: str | None = None
    direccion_oficial: str | None = None
    calle: str | None = None
    numero: str | None = None
    rol_propiedad: str | None = None


class CertRecepcionFinalDomExtraction(BaseModel):
    """Doc 3 §10 - Cert. Recepción Final (DOM)."""
    model_config = ConfigDict(extra="allow")
    municipalidad: str | None = None
    fecha_emision: str | None = None
    permiso_edificacion_n: str | None = None
    fecha_recepcion: str | None = None
    estado_recepcion: Literal["total", "parcial", "sin_recepcion"] | None = None
    superficie_construida_m2: float | None = None


# ── Persona Jurídica ───────────────────────────────────────────────────────

class ERutSiiExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    rut_sociedad: str | None = None
    razon_social: str | None = None
    fecha_emision: str | None = None
    actividad_economica: str | None = None


class EscrituraConstitucionSocialExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    fecha_otorgamiento: str | None = None
    notario_nombre: str | None = None
    razon_social: str | None = None
    rut_sociedad: str | None = None
    tipo_sociedad: Literal["spa", "sa", "ltda", "eirl", "otro"] | None = None
    capital_clp: int | None = None
    socios: list[dict] = Field(default_factory=list)
    origen: Literal["res_empresa_dia", "tradicional_cbr"] | None = None


class CertVigenciaPoderesExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    razon_social: str | None = None
    rut_sociedad: str | None = None
    fecha_emision: str | None = None  # validar < 30 días
    representantes: list[dict] = Field(
        default_factory=list,
        description="[{nombre, rut, facultades:[comprar,vender,enajenar,hipotecar,dar_garantia]}]",
    )
    condiciones_poder: Literal["actuacion_conjunta", "individual", "directorio", "junta_accionistas"] | None = None
    limite_uf: float | None = None
    limite_clp: int | None = None


# ── Condominio ─────────────────────────────────────────────────────────────

class CertDeudaGastosComunesExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    fecha_emision: str | None = None
    administrador_nombre: str | None = None
    administrador_rut: str | None = None
    emisor: Literal["administrador_profesional", "presidente_comite"] | None = None
    monto_deuda_clp: int | None = None
    cuotas_pendientes: int | None = None
    inscripcion_reglamento: dict | None = None  # {foja, numero, anio, cbr}


class ActaAsambleaCopropietariosExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    fecha_asamblea: str | None = None
    notaria: str | None = None
    administrador_nombrado: str | None = None
    presidente_comite_nombrado: str | None = None
    foja_inscripcion: str | None = None
    numero_inscripcion: str | None = None
    anio_inscripcion: int | None = None


# ── SERVIU / Subsidio ──────────────────────────────────────────────────────

class ResolucionServiuExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    numero_resolucion: str | None = None
    fecha_emision: str | None = None
    plazo_prohibicion_anios: int | None = None  # 5, 10, 15
    fecha_vencimiento_prohibicion: str | None = None
    autoriza_venta_anticipada: bool | None = None
    alza_prohibicion: bool | None = None


# ── Tribunales (Menores / Incapaces) ───────────────────────────────────────

class SentenciaJudicialExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    tribunal: str | None = None
    causa_rit_rol: str | None = None  # formato C-XXXX-YYYY
    fecha_resolucion: str | None = None
    menor_nombre: str | None = None
    menor_rut: str | None = None
    tipo_autorizacion: Literal[
        "venta_publica_subasta", "venta_directa", "venta_con_retencion"
    ] | None = None
    ejecutoriada: bool | None = None  # bloqueante


class CertEjecutoriaExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    tribunal: str | None = None
    causa_rit_rol: str | None = None
    fecha_emision: str | None = None
    sentencia_firme: bool | None = None


# ── Rural / SAG ────────────────────────────────────────────────────────────

class CertSubdivisionSagExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    numero_resolucion: str | None = None
    fecha_aprobacion: str | None = None
    superficie_predial_m2: float | None = None  # debe ser >= 5000
    cumple_minimo_legal: bool | None = None
    plano_archivado: dict | None = None  # {numero, anio, cbr}
    prohibicion_uso_urbano_comercial: bool | None = None


# ── Indígena ───────────────────────────────────────────────────────────────

class CertConadiExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    numero_resolucion: str | None = None
    fecha_emision: str | None = None
    persona_nombre: str | None = None
    persona_rut: str | None = None
    rol: Literal["vendedor", "comprador"] | None = None
    calidad_indigena_acreditada: bool | None = None
    etnia: str | None = None  # mapuche, aymara, …


# ── Herencia ───────────────────────────────────────────────────────────────

class CertPosesionEfectivaExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    organismo: Literal["registro_civil", "tribunal"] | None = None
    numero_resolucion: str | None = None
    fecha_resolucion: str | None = None
    causante_nombre: str | None = None
    causante_rut: str | None = None
    fecha_defuncion: str | None = None
    herederos: list[dict] = Field(default_factory=list)
    inscripcion_especial_herencia: dict | None = None  # {foja, numero, anio, cbr}


class CertExencionHerenciaSiiExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")
    numero_resolucion: str | None = None
    fecha_emision: str | None = None
    causante_nombre: str | None = None
    causante_rut: str | None = None
    estado: Literal["exento", "pagado"] | None = None
    monto_pagado_clp: int | None = None


# ── Planos / Plan Regulador (legacy) ───────────────────────────────────────

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


class CertMunicipalExtraction(BaseModel):
    """Schema legacy - cuando el clasificador devuelve cert_municipal genérico."""
    model_config = ConfigDict(extra="allow")
    municipalidad: str | None = None
    fecha_emision: str | None = None
    numero_municipal: str | None = None
    direccion_oficial: str | None = None
    no_expropiacion: bool | None = None
    recepcion_final: dict | None = None
    permiso_edificacion: dict | None = None


# ─────────── Wrapper de salida ───────────

class ExtractionResult(BaseModel):
    """Wrapper común que devuelven los endpoints."""
    model_config = ConfigDict(extra="allow")

    tipo: TipoDocumento
    datos: dict
    confianza: float = 0.0
    spans: list[dict] = []
    schema_version: str = "v1"  # bump por el cambio de spec


# ─────────── Anchors (trazabilidad campo↔documento) ───────────
# Los anchors permiten al abogado AGREGAR/EDITAR/BORRAR la conexión entre
# un campo extraído y el span del PDF que lo respalda. La evidencia
# auto-generada por el extractor también es un anchor (origen='auto').

class CreateAnchorRequest(BaseModel):
    """Crea un anchor manual sobre una extracción existente.

    El usuario debe entregar al menos `campo` y una ubicación válida —
    page+char_start+char_end (pdf_text) o page+bboxes (ocr). El backend
    no verifica que las coordenadas estén dentro del documento; eso es
    responsabilidad de la UI que las genera vía window.getSelection o
    dibujando rects sobre el canvas.
    """
    model_config = ConfigDict(extra="forbid")
    campo: str = Field(..., min_length=1, description="Path del campo: 'titular.rut'")
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    snippet: str | None = None
    fuente_texto: Literal["pdf_text", "ocr"] = "pdf_text"
    bboxes: list[list[float]] | None = Field(
        None,
        description="Array de [x0,y0,x1,y1] en PUNTOS PDF; obligatorio si fuente='ocr'",
    )
    id_ocr: int | None = Field(
        None,
        description="FK a dt_ocr_pagina cuando fuente='ocr'; permite trazar al OCR exacto.",
    )


class UpdateAnchorRequest(BaseModel):
    """Patch parcial. Solo los campos provistos se modifican."""
    model_config = ConfigDict(extra="forbid")
    campo: str | None = None
    snippet: str | None = None
    estado: Literal["propuesto", "confirmado", "rechazado"] | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    # `bboxes` aquí tiene tres estados: ausente (no cambiar), [] / None
    # (poner a NULL), array (reemplazar). Pydantic no distingue ausente vs
    # None — usamos el `bboxes_set` interno en el handler. Para que el
    # usuario pueda mandar null y limpiar, exponemos un campo separado.
    bboxes: list[list[float]] | None = None
    clear_bboxes: bool = Field(
        False,
        description="True para poner bboxes a NULL (al cambiar de OCR a pdf_text).",
    )
