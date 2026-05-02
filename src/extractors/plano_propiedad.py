"""Planos arquitectónicos / topográficos / de loteo."""
from src.extractors.base import BaseExtractor


class PlanoPropiedadExtractor(BaseExtractor):
    tipo = "plano_propiedad"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave del cajetín y cuadro de superficies del plano: tipo "
            "(loteo, arquitectónico, topográfico), superficie total, superficie construida, "
            "deslindes (norte/sur/oriente/poniente), profesional autor (nombre + colegio + RUT) "
            "y fecha del plano."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "Plano de Loteo. Comuna Las Condes. Superficie total: 320,5 m². "
                    "Superficie construida: 78,5 m². Deslindes: NORTE: pasaje 12 m; SUR: predio Rol 12.345-8; "
                    "ORIENTE: Av. Apoquindo en línea quebrada; PONIENTE: predio Rol 12.345-6. "
                    "Profesional: Arq. Carolina Vega, Reg. Nacional 5678. Fecha: marzo 2018."
                ),
                "extractions": [
                    {"extraction_class": "tipo_plano", "extraction_text": "Loteo", "attributes": {}},
                    {"extraction_class": "superficie_total_m2", "extraction_text": "320,5", "attributes": {}},
                    {"extraction_class": "superficie_construida_m2", "extraction_text": "78,5", "attributes": {}},
                    {
                        "extraction_class": "deslindes",
                        "extraction_text": "NORTE: pasaje 12 m; SUR: predio Rol 12.345-8; ORIENTE: Av. Apoquindo; PONIENTE: predio Rol 12.345-6",
                        "attributes": {
                            "norte": "pasaje 12 m",
                            "sur": "predio Rol 12.345-8",
                            "oriente": "Av. Apoquindo",
                            "poniente": "predio Rol 12.345-6",
                        },
                    },
                    {"extraction_class": "profesional", "extraction_text": "Arq. Carolina Vega, Reg. Nac. 5678", "attributes": {}},
                    {"extraction_class": "fecha_plano", "extraction_text": "marzo 2018", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tipo_plano": None, "superficie_total_m2": None, "superficie_construida_m2": None,
            "deslindes": None, "profesional": None, "fecha_plano": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            attrs = getattr(ex, "attributes", None) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})

            if cls in out:
                if cls.startswith("superficie_"):
                    try:
                        out[cls] = float(str(txt).replace(",", "."))
                    except (ValueError, TypeError):
                        out[cls] = None
                elif cls == "deslindes":
                    out[cls] = {"raw": str(txt), **(attrs or {})}
                elif txt is not None:
                    out[cls] = str(txt).strip()
        return out
