"""Plan regulador comunal."""
from src.extractors.base import BaseExtractor


class PlanReguladorExtractor(BaseExtractor):
    tipo = "plan_regulador"

    def prompt(self) -> str:
        return (
            "Extrae datos del Plan Regulador Comunal o certificado de informaciones previas: "
            "comuna, zonificación, usos permitidos, altura máxima, coeficiente de "
            "constructibilidad, coeficiente de ocupación de suelo, densidad máxima."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "Plan Regulador Comunal de Las Condes. Zona ZH-1. "
                    "Usos permitidos: residencial, oficina, comercio menor. "
                    "Altura máxima: 7 pisos. Coeficiente de constructibilidad: 2,5. "
                    "Coeficiente de ocupación de suelo: 0,5. Densidad máxima: 600 hab/há."
                ),
                "extractions": [
                    {"extraction_class": "comuna", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "zonificacion", "extraction_text": "ZH-1", "attributes": {}},
                    {"extraction_class": "uso_permitido", "extraction_text": "residencial", "attributes": {}},
                    {"extraction_class": "uso_permitido", "extraction_text": "oficina", "attributes": {}},
                    {"extraction_class": "uso_permitido", "extraction_text": "comercio menor", "attributes": {}},
                    {"extraction_class": "altura_maxima", "extraction_text": "7 pisos", "attributes": {}},
                    {"extraction_class": "coef_constructibilidad", "extraction_text": "2,5", "attributes": {}},
                    {"extraction_class": "coef_ocupacion_suelo", "extraction_text": "0,5", "attributes": {}},
                    {"extraction_class": "densidad_max", "extraction_text": "600 hab/há", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "comuna": None, "zonificacion": None, "usos_permitidos": [],
            "altura_maxima": None, "coef_constructibilidad": None,
            "coef_ocupacion_suelo": None, "densidad_max": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls == "uso_permitido":
                out["usos_permitidos"].append(txt)
            elif cls in out:
                if cls.startswith("coef_"):
                    try:
                        out[cls] = float(txt.replace(",", "."))
                    except ValueError:
                        out[cls] = None
                else:
                    out[cls] = txt
        return out
