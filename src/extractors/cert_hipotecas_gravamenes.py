"""
Certificado de Hipotecas y Gravámenes — GP (CBR).
Doc 3 §4 del spec del abogado.

Clasificación de gravámenes en TIERS:
  - tier_1: embargos, precautorias, litigios, bien familiar  (BLOQUEO ABSOLUTO)
  - tier_2: hipotecas/prohibiciones de bancos                (subsanable, alzamiento)
  - tier_3: limpio                                            (sin anotaciones)
"""
from src.extractors.base import BaseExtractor

TIER_1_KEYWORDS = ("embargo", "precautoria", "medida precautoria", "litigio", "bien familiar")


class CertHipotecasExtractor(BaseExtractor):
    tipo = "cert_hipotecas_gravamenes"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave de este Certificado de Hipotecas y Gravámenes (GP) "
            "emitido por el Conservador de Bienes Raíces de Chile. Identifica:\n"
            "  - cbr_emisor, fecha_emision, foja, numero_inscripcion, anio_inscripcion\n"
            "  - rut_dueno (RUT del titular del inmueble)\n"
            "  - hipoteca: por cada hipoteca activa, devuelve una extracción con el "
            "nombre del acreedor (banco) y, si aparecen, foja/numero/anio de la inscripción\n"
            "  - prohibicion: por cada prohibición de enajenar/gravar\n"
            "  - embargo: por cada embargo (Tier 1, BLOQUEANTE)\n"
            "  - precautoria: por cada medida precautoria\n"
            "  - bien_familiar: si menciona declaración de Bien Familiar\n"
            "  - interdiccion: si aparece\n"
            "Si el certificado dice 'no registra hipotecas, gravámenes ni prohibiciones', "
            "devuelve extraction_class='libre_de_gravamenes' con texto 'sí'."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "CONSERVADOR DE BIENES RAÍCES DE SANTIAGO\n"
                    "Certificado de Hipotecas, Gravámenes, Prohibiciones e Interdicciones\n"
                    "Inmueble: Foja 234 Nº 567 año 2018. Titular: María Pérez Vega, RUT 11.222.333-4\n"
                    "Se certifica que el inmueble registra:\n"
                    " - Una HIPOTECA a favor de Banco BICE, inscrita a fojas 50 Nº 100 del año 2020.\n"
                    " - PROHIBICIÓN de enajenar a favor de Banco BICE.\n"
                    "Emitido el 12 de marzo de 2026."
                ),
                "extractions": [
                    {"extraction_class": "cbr_emisor", "extraction_text": "CBR de Santiago", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "12 de marzo de 2026", "attributes": {}},
                    {"extraction_class": "foja", "extraction_text": "234", "attributes": {}},
                    {"extraction_class": "numero_inscripcion", "extraction_text": "567", "attributes": {}},
                    {"extraction_class": "anio_inscripcion", "extraction_text": "2018", "attributes": {}},
                    {"extraction_class": "rut_dueno", "extraction_text": "11.222.333-4", "attributes": {}},
                    {"extraction_class": "hipoteca", "extraction_text": "Banco BICE",
                     "attributes": {"foja_hip": "50", "numero_hip": "100", "anio_hip": "2020"}},
                    {"extraction_class": "prohibicion", "extraction_text": "prohibición de enajenar a favor de Banco BICE", "attributes": {}},
                ],
            },
            {
                "text": (
                    "CBR de Providencia. Inmueble Foja 100 Nº 200 año 2015. "
                    "Se certifica que NO REGISTRA hipotecas, gravámenes, prohibiciones ni "
                    "interdicciones a la fecha. Emitido el 5 de mayo de 2026."
                ),
                "extractions": [
                    {"extraction_class": "cbr_emisor", "extraction_text": "CBR de Providencia", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "5 de mayo de 2026", "attributes": {}},
                    {"extraction_class": "foja", "extraction_text": "100", "attributes": {}},
                    {"extraction_class": "numero_inscripcion", "extraction_text": "200", "attributes": {}},
                    {"extraction_class": "anio_inscripcion", "extraction_text": "2015", "attributes": {}},
                    {"extraction_class": "libre_de_gravamenes", "extraction_text": "sí", "attributes": {}},
                ],
            },
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "cbr_emisor": None, "fecha_emision": None,
            "foja": None, "numero_inscripcion": None, "anio_inscripcion": None,
            "rut_dueno": None,
            "hipotecas_vigentes": [], "prohibiciones": [], "embargos": [],
            "interdicciones": [], "bien_familiar": None,
            "tier_clasificacion": None, "libre_de_gravamenes": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            attrs = getattr(ex, "attributes", {}) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})
            if not cls or not txt:
                continue

            if cls == "anio_inscripcion":
                digits = "".join(c for c in str(txt) if c.isdigit())
                out["anio_inscripcion"] = int(digits) if digits else None
            elif cls == "hipoteca":
                out["hipotecas_vigentes"].append({
                    "acreedor": str(txt).strip(),
                    "foja": attrs.get("foja_hip"),
                    "numero": attrs.get("numero_hip"),
                    "anio": attrs.get("anio_hip"),
                })
            elif cls == "prohibicion":
                out["prohibiciones"].append(str(txt).strip())
            elif cls == "embargo":
                out["embargos"].append(str(txt).strip())
            elif cls == "precautoria":
                out["embargos"].append(f"Precautoria: {str(txt).strip()}")
            elif cls == "interdiccion":
                out["interdicciones"].append(str(txt).strip())
            elif cls == "bien_familiar":
                out["bien_familiar"] = True
            elif cls == "libre_de_gravamenes":
                out["libre_de_gravamenes"] = str(txt).strip().lower() in ("true", "sí", "si", "1", "verdadero")
            elif cls in out:
                out[cls] = str(txt).strip()

        out["tier_clasificacion"] = _clasificar_tier(out)
        if out["libre_de_gravamenes"] is None:
            out["libre_de_gravamenes"] = (out["tier_clasificacion"] == "tier_3")
        return out


def _clasificar_tier(datos: dict) -> str:
    """Aplica la regla del abogado: tier_1 > tier_2 > tier_3."""
    if datos.get("embargos") or datos.get("interdicciones") or datos.get("bien_familiar"):
        return "tier_1"
    for p in datos.get("prohibiciones", []):
        if any(kw in p.lower() for kw in TIER_1_KEYWORDS):
            return "tier_1"
    if datos.get("hipotecas_vigentes") or datos.get("prohibiciones"):
        return "tier_2"
    return "tier_3"
