"""Certificado de avalúo fiscal (SII)."""
from src.extractors.base import BaseExtractor


class CertAvaluoSiiExtractor(BaseExtractor):
    tipo = "cert_avaluo_sii"

    def prompt(self) -> str:
        return (
            "Extrae los datos del Certificado de Avalúo Fiscal del Servicio de Impuestos "
            "Internos chileno: rol de avalúo, comuna, fecha de emisión, avalúo total, terreno y "
            "construcción (en pesos chilenos), superficies (terreno y construida), destino "
            "(habitacional, comercial…), exención de impuesto territorial."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "SERVICIO DE IMPUESTOS INTERNOS. Certificado de Avalúo Fiscal. "
                    "Rol de avalúo: 12345-7. Comuna: Las Condes. Emitido: 28-04-2026. "
                    "Avalúo total: $145.230.000. Avalúo terreno: $90.000.000. Avalúo construcción: $55.230.000. "
                    "Superficie terreno: 0 m². Superficie construida: 78,5 m². Destino: Habitacional. "
                    "Exento contribuciones: Sí (avalúo bajo tramo)."
                ),
                "extractions": [
                    {"extraction_class": "rol_avaluo", "extraction_text": "12345-7", "attributes": {}},
                    {"extraction_class": "comuna", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "28-04-2026", "attributes": {}},
                    {"extraction_class": "avaluo_total_clp", "extraction_text": "145.230.000", "attributes": {}},
                    {"extraction_class": "avaluo_terreno_clp", "extraction_text": "90.000.000", "attributes": {}},
                    {"extraction_class": "avaluo_construccion_clp", "extraction_text": "55.230.000", "attributes": {}},
                    {"extraction_class": "superficie_construida_m2", "extraction_text": "78,5", "attributes": {}},
                    {"extraction_class": "destino", "extraction_text": "Habitacional", "attributes": {}},
                    {"extraction_class": "exento_iva", "extraction_text": "Sí", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "rol_avaluo": None, "comuna": None, "fecha_emision": None,
            "avaluo_total_clp": None, "avaluo_terreno_clp": None, "avaluo_construccion_clp": None,
            "superficie_terreno_m2": None, "superficie_construida_m2": None,
            "destino": None, "exento_iva": None,
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
            elif cls == "exento_iva":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out
