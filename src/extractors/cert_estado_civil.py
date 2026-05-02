"""
Certificados del Registro Civil — matrimonio, unión civil, soltería, defunción.
Doc 3 §2 del spec del abogado.

Comparte schema y extractor; el campo `tipo_cert` distingue cuál es. Cada
código del catálogo tiene su clase wrapper para que get_extractor mapee bien.
"""
from src.extractors.base import BaseExtractor


class CertEstadoCivilBase(BaseExtractor):
    """Base genérico para certificados del Registro Civil."""

    DEFAULT_TIPO_CERT: str = "matrimonio"

    def prompt(self) -> str:
        return (
            "Extrae datos de este certificado del Servicio de Registro Civil chileno. "
            "Puede ser de matrimonio, unión civil (AUC), soltería, viudez o defunción.\n"
            "Identifica:\n"
            "  - tipo_cert: 'matrimonio', 'union_civil', 'soltería', 'viudez' o 'defuncion'\n"
            "  - parte_a_nombre + parte_a_rut: primer titular del certificado\n"
            "  - parte_b_nombre + parte_b_rut: cónyuge / conviviente civil / cónyuge fallecido\n"
            "    (en defunción, parte_a es el difunto)\n"
            "  - fecha_celebracion: fecha del matrimonio/unión\n"
            "  - regimen: 'sociedad_conyugal', 'separacion_total_de_bienes', "
            "'participacion_gananciales' o 'no_aplica'\n"
            "  - subinscripcion: 'separacion_total_de_bienes', 'participacion_gananciales', "
            "'divorcio' o 'sin_subinscripcion'\n"
            "  - fecha_subinscripcion: si aparece (separación, divorcio)\n"
            "  - fecha_defuncion: solo en cert. defunción / viudez"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "REPÚBLICA DE CHILE — SERVICIO DE REGISTRO CIVIL E IDENTIFICACIÓN\n"
                    "CERTIFICADO DE MATRIMONIO\n"
                    "Cónyuges: PEDRO SOTO ROJAS, RUT 11.111.111-1 y MARÍA PÉREZ VEGA, RUT 12.222.222-2\n"
                    "Fecha de matrimonio: 14 de febrero de 2010\n"
                    "Régimen: Sociedad Conyugal\n"
                    "Subinscripción al margen: divorcio el 10 de junio de 2020"
                ),
                "extractions": [
                    {"extraction_class": "tipo_cert", "extraction_text": "matrimonio", "attributes": {}},
                    {"extraction_class": "parte_a_nombre", "extraction_text": "PEDRO SOTO ROJAS", "attributes": {}},
                    {"extraction_class": "parte_a_rut", "extraction_text": "11.111.111-1", "attributes": {}},
                    {"extraction_class": "parte_b_nombre", "extraction_text": "MARÍA PÉREZ VEGA", "attributes": {}},
                    {"extraction_class": "parte_b_rut", "extraction_text": "12.222.222-2", "attributes": {}},
                    {"extraction_class": "fecha_celebracion", "extraction_text": "14 de febrero de 2010", "attributes": {}},
                    {"extraction_class": "regimen", "extraction_text": "sociedad_conyugal", "attributes": {}},
                    {"extraction_class": "subinscripcion", "extraction_text": "divorcio", "attributes": {}},
                    {"extraction_class": "fecha_subinscripcion", "extraction_text": "10 de junio de 2020", "attributes": {}},
                ],
            },
            {
                "text": (
                    "REGISTRO CIVIL — CERTIFICADO DE DEFUNCIÓN\n"
                    "Difunto: JUAN PÉREZ ROJAS, RUT 5.555.555-5\n"
                    "Fecha de defunción: 22 de marzo de 2024"
                ),
                "extractions": [
                    {"extraction_class": "tipo_cert", "extraction_text": "defuncion", "attributes": {}},
                    {"extraction_class": "parte_a_nombre", "extraction_text": "JUAN PÉREZ ROJAS", "attributes": {}},
                    {"extraction_class": "parte_a_rut", "extraction_text": "5.555.555-5", "attributes": {}},
                    {"extraction_class": "fecha_defuncion", "extraction_text": "22 de marzo de 2024", "attributes": {}},
                ],
            },
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tipo_cert": None,
            "parte_a_nombre": None, "parte_a_rut": None,
            "parte_b_nombre": None, "parte_b_rut": None,
            "fecha_celebracion": None,
            "regimen": None, "subinscripcion": None, "fecha_subinscripcion": None,
            "fecha_defuncion": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            out[cls] = str(txt).strip()

        # Default tipo_cert según la subclase si el LLM no lo devolvió
        if not out["tipo_cert"]:
            out["tipo_cert"] = self.DEFAULT_TIPO_CERT
        return out


# Clases concretas (una por código del catálogo)
class CertMatrimonioExtractor(CertEstadoCivilBase):
    tipo = "cert_matrimonio"
    DEFAULT_TIPO_CERT = "matrimonio"


class CertUnionCivilExtractor(CertEstadoCivilBase):
    tipo = "cert_union_civil"
    DEFAULT_TIPO_CERT = "union_civil"


class CertSolteriaExtractor(CertEstadoCivilBase):
    tipo = "cert_solteria"
    DEFAULT_TIPO_CERT = "solteria"


class CertDefuncionExtractor(CertEstadoCivilBase):
    tipo = "cert_defuncion"
    DEFAULT_TIPO_CERT = "defuncion"


class DeclJuradaSolteriaExtractor(BaseExtractor):
    """
    Declaración Jurada de Soltería — Word/impresa con firma manuscrita.
    Doc 2 del abogado: 'la IA debe aprender a detectar la presencia de una firma física'.
    """

    tipo = "decl_jurada_solteria"

    def prompt(self) -> str:
        return (
            "Esta es una declaración jurada simple (NO notarial) de soltería. Es típicamente "
            "un Word impreso, firmado a mano y escaneado. Extrae:\n"
            "  - declarante_nombre + declarante_rut\n"
            "  - fecha_declaracion\n"
            "  - tiene_firma_manuscrita: indica 'sí' si el documento muestra una firma manuscrita "
            "(trazo de pluma, no impresa) — esto requiere inferir de pistas como 'firmado y "
            "escaneado', 'firma:' seguido de espacio, etc."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "DECLARACIÓN JURADA SIMPLE\n"
                    "Yo, JOSÉ MARÍA AGUILAR LARA, RUT 16.789.012-3, declaro bajo juramento "
                    "que mi estado civil es SOLTERO.\n"
                    "Santiago, 10 de marzo de 2026.\n"
                    "[Firma manuscrita escaneada]"
                ),
                "extractions": [
                    {"extraction_class": "declarante_nombre", "extraction_text": "JOSÉ MARÍA AGUILAR LARA", "attributes": {}},
                    {"extraction_class": "declarante_rut", "extraction_text": "16.789.012-3", "attributes": {}},
                    {"extraction_class": "fecha_declaracion", "extraction_text": "10 de marzo de 2026", "attributes": {}},
                    {"extraction_class": "tiene_firma_manuscrita", "extraction_text": "sí", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "declarante_nombre": None, "declarante_rut": None,
            "fecha_declaracion": None, "tiene_firma_manuscrita": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "tiene_firma_manuscrita":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out
