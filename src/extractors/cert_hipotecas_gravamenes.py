"""Certificado de hipotecas, gravámenes, prohibiciones e interdicciones (CBR)."""
from src.extractors.base import BaseExtractor


class CertHipotecasExtractor(BaseExtractor):
    tipo = "cert_hipotecas_gravamenes"

    def prompt(self) -> str:
        return (
            "Extrae las hipotecas, gravámenes, prohibiciones e interdicciones que registra "
            "este certificado del Conservador de Bienes Raíces. Para cada hipoteca extrae el "
            "acreedor, monto y fecha. Si el certificado dice 'libre de gravámenes' marca el "
            "campo correspondiente. Cita literalmente cada dato."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "CBR de Santiago. Certificado de Hipotecas, Gravámenes, Prohibiciones e Interdicciones. "
                    "26 de abril de 2026. La propiedad registra a) Hipoteca a favor de Banco Bice, "
                    "por UF 3.200, inscrita a fojas 4321 N° 8765 de 2020. b) Prohibición de gravar y enajenar "
                    "a favor de Banco Bice asociada a la hipoteca anterior. No registra otros gravámenes."
                ),
                "extractions": [
                    {"extraction_class": "cbr_emisor", "extraction_text": "CBR de Santiago", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "26 de abril de 2026", "attributes": {}},
                    {
                        "extraction_class": "hipoteca",
                        "extraction_text": "Hipoteca Banco Bice UF 3.200",
                        "attributes": {"acreedor": "Banco Bice", "monto_uf": "3.200", "foja": "4321", "numero": "8765", "anio": "2020"},
                    },
                    {"extraction_class": "prohibicion", "extraction_text": "Prohibición de gravar y enajenar a favor de Banco Bice", "attributes": {}},
                    {"extraction_class": "libre_de_gravamenes", "extraction_text": "false", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "cbr_emisor": None, "fecha_emision": None, "foja": None,
            "hipotecas_vigentes": [], "prohibiciones": [], "gravamenes": [], "interdicciones": [],
            "libre_de_gravamenes": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            attrs = getattr(ex, "attributes", None) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})

            if cls == "hipoteca":
                out["hipotecas_vigentes"].append({"descripcion": str(txt), **(attrs or {})})
            elif cls == "prohibicion":
                out["prohibiciones"].append(str(txt))
            elif cls == "gravamen":
                out["gravamenes"].append(str(txt))
            elif cls == "interdiccion":
                out["interdicciones"].append(str(txt))
            elif cls == "libre_de_gravamenes":
                out["libre_de_gravamenes"] = str(txt).strip().lower() in ("true", "sí", "si", "1", "verdadero")
            elif cls in out and txt:
                out[cls] = str(txt).strip()
        return out
