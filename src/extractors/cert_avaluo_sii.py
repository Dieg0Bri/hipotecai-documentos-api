"""
Certificado de Avalúo Fiscal (SII).
Doc 3 §8 del spec del abogado.
"""
from src.extractors.base import BaseExtractor


class CertAvaluoSiiExtractor(BaseExtractor):
    tipo = "cert_avaluo_sii"

    def prompt(self) -> str:
        return (
            "Extrae los datos del Certificado de Avalúo Fiscal del Servicio de Impuestos "
            "Internos chileno (Doc 3 §8 del estudio de títulos):\n"
            "  - rol_avaluo: en formato XXXX-YY (ej. 12345-7)\n"
            "  - comuna: comuna SII\n"
            "  - fecha_emision\n"
            "  - avaluo_total_clp, avaluo_terreno_clp, avaluo_construccion_clp (en pesos)\n"
            "  - superficie_terreno_m2, superficie_construida_m2\n"
            "  - destino (Habitacional, Agrícola, Comercial, Industrial, etc.)\n"
            "  - condicion: 'exento' o 'afecto' (a impuesto territorial / contribuciones)\n"
            "  - semestre: ej. '2026-1'"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "SERVICIO DE IMPUESTOS INTERNOS. Certificado de Avalúo Fiscal. "
                    "Semestre 2026-1. Rol de avalúo: 12345-7. Comuna: Las Condes. "
                    "Emitido: 28-04-2026. Avalúo total: $145.230.000. Avalúo terreno: $90.000.000. "
                    "Avalúo construcción: $55.230.000. Superficie construida: 78,5 m². "
                    "Destino: Habitacional. Condición: AFECTO."
                ),
                "extractions": [
                    {"extraction_class": "rol_avaluo", "extraction_text": "12345-7", "attributes": {}},
                    {"extraction_class": "comuna", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "28-04-2026", "attributes": {}},
                    {"extraction_class": "semestre", "extraction_text": "2026-1", "attributes": {}},
                    {"extraction_class": "avaluo_total_clp", "extraction_text": "145.230.000", "attributes": {}},
                    {"extraction_class": "avaluo_terreno_clp", "extraction_text": "90.000.000", "attributes": {}},
                    {"extraction_class": "avaluo_construccion_clp", "extraction_text": "55.230.000", "attributes": {}},
                    {"extraction_class": "superficie_construida_m2", "extraction_text": "78,5", "attributes": {}},
                    {"extraction_class": "destino", "extraction_text": "Habitacional", "attributes": {}},
                    {"extraction_class": "condicion", "extraction_text": "afecto", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "rol_avaluo": None, "comuna": None, "fecha_emision": None, "semestre": None,
            "avaluo_total_clp": None, "avaluo_terreno_clp": None, "avaluo_construccion_clp": None,
            "superficie_terreno_m2": None, "superficie_construida_m2": None,
            "destino": None, "condicion": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls.startswith("avaluo_"):
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls.startswith("superficie_"):
                try:
                    out[cls] = float(txt.replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls == "condicion":
                low = txt.lower()
                if "exent" in low:
                    out[cls] = "exento"
                elif "afecto" in low or "afect" in low:
                    out[cls] = "afecto"
            else:
                out[cls] = txt
        return out
