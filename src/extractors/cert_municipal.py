"""Certificados municipales (DOM): número, no expropiación, recepción final."""
from src.extractors.base import BaseExtractor


class CertMunicipalExtractor(BaseExtractor):
    tipo = "cert_municipal"

    def prompt(self) -> str:
        return (
            "Extrae los datos del certificado municipal chileno (DOM). Puede contener: "
            "certificado de número, certificado de no expropiación, certificado de recepción "
            "final, permiso de edificación. Identifica municipalidad, fecha de emisión, "
            "número municipal oficial, dirección oficial y los flags pertinentes."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "ILUSTRE MUNICIPALIDAD DE LAS CONDES. Dirección de Obras Municipales. "
                    "Certificado de Número y de No Expropiación. 22 de abril de 2026. "
                    "Se certifica que el inmueble ubicado en Av. Apoquindo 5400 oficina 1404 "
                    "tiene asignado el número municipal 5400 y NO se encuentra afecto a expropiación municipal. "
                    "Recepción final otorgada con fecha 30-12-2018, según permiso 245-2017."
                ),
                "extractions": [
                    {"extraction_class": "municipalidad", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "22 de abril de 2026", "attributes": {}},
                    {"extraction_class": "numero_municipal", "extraction_text": "5400", "attributes": {}},
                    {"extraction_class": "direccion_oficial", "extraction_text": "Av. Apoquindo 5400 oficina 1404", "attributes": {}},
                    {"extraction_class": "no_expropiacion", "extraction_text": "true", "attributes": {}},
                    {
                        "extraction_class": "recepcion_final",
                        "extraction_text": "30-12-2018",
                        "attributes": {"otorgada": "true", "fecha": "30-12-2018", "permiso": "245-2017"},
                    },
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "municipalidad": None, "fecha_emision": None, "numero_municipal": None,
            "direccion_oficial": None, "no_expropiacion": None,
            "recepcion_final": None, "permiso_edificacion": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            attrs = getattr(ex, "attributes", None) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})

            if cls in out:
                if cls == "no_expropiacion":
                    out[cls] = str(txt).strip().lower() in ("true", "sí", "si", "1")
                elif cls in ("recepcion_final", "permiso_edificacion"):
                    out[cls] = {"raw": str(txt), **(attrs or {})}
                elif txt is not None:
                    out[cls] = str(txt).strip()
        return out
