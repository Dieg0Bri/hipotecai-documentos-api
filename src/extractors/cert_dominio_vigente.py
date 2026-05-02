"""Certificado de dominio vigente (CBR)."""
from src.extractors.base import BaseExtractor


class CertDominioVigenteExtractor(BaseExtractor):
    tipo = "cert_dominio_vigente"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave de este Certificado de Dominio Vigente emitido por el "
            "Conservador de Bienes Raíces de Chile. Identifica: CBR emisor, fecha de emisión, "
            "foja, número y año de inscripción, titular actual (nombre + RUT si aparece), "
            "rol de la propiedad, dirección y superficie. Cita literalmente cada dato."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "CONSERVADOR DE BIENES RAÍCES DE SANTIAGO. Certificado de Dominio Vigente. "
                    "Santiago, 15 de abril de 2026. Se certifica que la propiedad inscrita "
                    "a fojas 1234, número 5678, año 2018, ubicada en Av. Apoquindo 5400 dpto 1404, "
                    "Rol 12.345-7, comuna de Las Condes, figura inscrita a nombre de don "
                    "PEDRO LÓPEZ ROJAS, RUT 9.876.543-2."
                ),
                "extractions": [
                    {"extraction_class": "cbr_emisor", "extraction_text": "CBR de Santiago", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "15 de abril de 2026", "attributes": {}},
                    {"extraction_class": "foja", "extraction_text": "1234", "attributes": {}},
                    {"extraction_class": "numero_inscripcion", "extraction_text": "5678", "attributes": {}},
                    {"extraction_class": "anio_inscripcion", "extraction_text": "2018", "attributes": {}},
                    {"extraction_class": "titular_actual", "extraction_text": "PEDRO LÓPEZ ROJAS", "attributes": {}},
                    {"extraction_class": "titular_rut", "extraction_text": "9.876.543-2", "attributes": {}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "direccion", "extraction_text": "Av. Apoquindo 5400 dpto 1404, Las Condes", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "cbr_emisor": None, "fecha_emision": None, "foja": None,
            "numero_inscripcion": None, "anio_inscripcion": None,
            "titular_actual": None, "titular_rut": None,
            "rol_propiedad": None, "direccion": None, "superficie_m2": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if cls in out and txt:
                if cls == "anio_inscripcion":
                    digits = "".join(c for c in str(txt) if c.isdigit())
                    out[cls] = int(digits) if digits else None
                elif cls == "superficie_m2":
                    try:
                        out[cls] = float(str(txt).replace(",", "."))
                    except ValueError:
                        out[cls] = None
                else:
                    out[cls] = str(txt).strip()
        return out
