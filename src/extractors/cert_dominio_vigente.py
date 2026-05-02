"""
Certificado de Dominio Vigente (CBR).
Doc 3 §3 del spec del abogado.
"""
from src.extractors.base import BaseExtractor


class CertDominioVigenteExtractor(BaseExtractor):
    tipo = "cert_dominio_vigente"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave de este Certificado de Dominio Vigente emitido por el "
            "Conservador de Bienes Raíces (CBR) de Chile. Debes identificar:\n"
            "  - cbr_emisor: nombre completo del Conservador (ej. 'CBR de Las Condes')\n"
            "  - fecha_emision: día en que se emitió el certificado\n"
            "  - foja, numero_inscripcion, anio_inscripcion: ubicación de la inscripción ACTUAL\n"
            "  - propietario: nombre y RUT de cada titular (puede haber varios)\n"
            "  - rol_propiedad, direccion, superficie_m2\n"
            "  - cita_titulo_anterior_*: foja, numero, año y CBR del título anterior (si lo cita)\n"
            "Cita literalmente cada dato. Si la propiedad tiene varios titulares, devuelve "
            "uno por cada titular en extracciones separadas con extraction_class='propietario'."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "CONSERVADOR DE BIENES RAÍCES DE LAS CONDES. Certificado de Dominio Vigente. "
                    "Las Condes, 15 de abril de 2026. Se certifica que la propiedad inscrita "
                    "a fojas 1234, número 5678, año 2018, ubicada en Av. Apoquindo 5400 dpto 1404, "
                    "Rol 12.345-7, comuna de Las Condes, figura inscrita a nombre de don "
                    "PEDRO LÓPEZ ROJAS, RUT 9.876.543-2. Adquisición proviene de inscripción "
                    "anterior a fojas 800, número 4321, año 2010, CBR de Las Condes."
                ),
                "extractions": [
                    {"extraction_class": "cbr_emisor", "extraction_text": "CBR de Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "15 de abril de 2026", "attributes": {}},
                    {"extraction_class": "foja", "extraction_text": "1234", "attributes": {}},
                    {"extraction_class": "numero_inscripcion", "extraction_text": "5678", "attributes": {}},
                    {"extraction_class": "anio_inscripcion", "extraction_text": "2018", "attributes": {}},
                    {"extraction_class": "propietario", "extraction_text": "PEDRO LÓPEZ ROJAS",
                     "attributes": {"rut": "9.876.543-2"}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "direccion", "extraction_text": "Av. Apoquindo 5400 dpto 1404, Las Condes", "attributes": {}},
                    {"extraction_class": "cita_titulo_anterior_foja", "extraction_text": "800", "attributes": {}},
                    {"extraction_class": "cita_titulo_anterior_numero", "extraction_text": "4321", "attributes": {}},
                    {"extraction_class": "cita_titulo_anterior_anio", "extraction_text": "2010", "attributes": {}},
                    {"extraction_class": "cita_titulo_anterior_cbr", "extraction_text": "CBR de Las Condes", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "cbr_emisor": None, "fecha_emision": None,
            "foja": None, "numero_inscripcion": None, "anio_inscripcion": None,
            "propietarios": [],
            "rol_propiedad": None, "direccion": None, "superficie_m2": None,
            "cita_titulo_anterior": None,
        }
        cita = {}

        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            attrs = getattr(ex, "attributes", {}) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})
            if not cls or not txt:
                continue

            if cls == "propietario":
                out["propietarios"].append({"nombre": str(txt).strip(), "rut": attrs.get("rut")})
            elif cls in ("anio_inscripcion",):
                digits = "".join(c for c in str(txt) if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "superficie_m2":
                try:
                    out[cls] = float(str(txt).replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls.startswith("cita_titulo_anterior_"):
                key = cls.replace("cita_titulo_anterior_", "")
                if key == "anio":
                    digits = "".join(c for c in str(txt) if c.isdigit())
                    cita["anio"] = int(digits) if digits else None
                else:
                    cita[key] = str(txt).strip()
            elif cls in out:
                out[cls] = str(txt).strip()

        if cita:
            out["cita_titulo_anterior"] = cita
        return out
