"""
Certificados emitidos por la Dirección de Obras Municipales (DOM) y SERVIU.
Doc 3 §10 del spec del abogado:
  - Cert. de No Expropiación (DOM o SERVIU)
  - Cert. de Número (DOM)
  - Cert. de Recepción Final (DOM)
"""
from src.extractors.base import BaseExtractor


class CertNoExpropiacionDomExtractor(BaseExtractor):
    """Cert. No Expropiación emitido por la DOM."""
    tipo = "cert_no_expropiacion_dom"
    EMISOR_DEFAULT = "dom"

    def prompt(self) -> str:
        return (
            "Extrae datos de este Certificado de No Expropiación emitido por la "
            "Dirección de Obras Municipales (DOM) o SERVIU:\n"
            "  - emisor: 'dom' o 'serviu'\n"
            "  - municipalidad (si DOM)\n"
            "  - fecha_emision\n"
            "  - rol_propiedad, direccion\n"
            "  - estado_afectacion: 'afecta' o 'no_afecta'\n"
            "  - motivo_afectacion: si afecta (ensanche calle, área verde, vialidad…)"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "MUNICIPALIDAD DE PROVIDENCIA — DIRECCIÓN DE OBRAS MUNICIPALES\n"
                    "Certificado de No Expropiación\n"
                    "Emitido: 5 de mayo de 2026\n"
                    "Rol: 12.345-7  Dirección: Av. Apoquindo 5400\n"
                    "Estado: NO SE ENCUENTRA AFECTA a expropiación municipal."
                ),
                "extractions": [
                    {"extraction_class": "emisor", "extraction_text": "dom", "attributes": {}},
                    {"extraction_class": "municipalidad", "extraction_text": "Providencia", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "5 de mayo de 2026", "attributes": {}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "direccion", "extraction_text": "Av. Apoquindo 5400", "attributes": {}},
                    {"extraction_class": "estado_afectacion", "extraction_text": "no_afecta", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "emisor": None, "municipalidad": None, "fecha_emision": None,
            "rol_propiedad": None, "direccion": None,
            "estado_afectacion": None, "motivo_afectacion": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "estado_afectacion":
                low = txt.lower().replace(" ", "_")
                if "no" in low and "afect" in low:
                    out[cls] = "no_afecta"
                elif "afect" in low:
                    out[cls] = "afecta"
            elif cls == "emisor":
                low = txt.lower()
                out[cls] = "serviu" if "serviu" in low else "dom"
            else:
                out[cls] = txt
        if not out["emisor"]:
            out["emisor"] = self.EMISOR_DEFAULT
        return out


class CertNoExpropiacionServiuExtractor(CertNoExpropiacionDomExtractor):
    """Mismo schema, emisor='serviu' por defecto."""
    tipo = "cert_no_expropiacion_serviu"
    EMISOR_DEFAULT = "serviu"


class CertNumeroDomExtractor(BaseExtractor):
    """Cert. de Número (DOM)."""
    tipo = "cert_numero_dom"

    def prompt(self) -> str:
        return (
            "Extrae datos del Certificado de Número emitido por la Dirección de Obras "
            "Municipales chilena:\n"
            "  - municipalidad\n"
            "  - fecha_emision\n"
            "  - direccion_oficial: dirección completa reportada\n"
            "  - calle, numero (separados)\n"
            "  - rol_propiedad"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "MUNICIPALIDAD DE LAS CONDES — DIRECCIÓN DE OBRAS MUNICIPALES\n"
                    "Certificado de Número\n"
                    "Emitido: 30-04-2026\n"
                    "Se certifica que la propiedad Rol 12.345-7 corresponde a la dirección oficial: "
                    "Av. Apoquindo Nº 5400."
                ),
                "extractions": [
                    {"extraction_class": "municipalidad", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "30-04-2026", "attributes": {}},
                    {"extraction_class": "direccion_oficial", "extraction_text": "Av. Apoquindo Nº 5400", "attributes": {}},
                    {"extraction_class": "calle", "extraction_text": "Av. Apoquindo", "attributes": {}},
                    {"extraction_class": "numero", "extraction_text": "5400", "attributes": {}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "municipalidad": None, "fecha_emision": None,
            "direccion_oficial": None, "calle": None, "numero": None,
            "rol_propiedad": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if cls in out and txt:
                out[cls] = str(txt).strip()
        return out


class CertRecepcionFinalDomExtractor(BaseExtractor):
    """Cert. de Recepción Final (DOM)."""
    tipo = "cert_recepcion_final_dom"

    def prompt(self) -> str:
        return (
            "Extrae datos del Certificado de Recepción Final emitido por la Dirección de "
            "Obras Municipales chilena (DOM):\n"
            "  - municipalidad\n"
            "  - fecha_emision\n"
            "  - permiso_edificacion_n: número del permiso de edificación\n"
            "  - fecha_recepcion: fecha en que se recepcionó la obra\n"
            "  - estado_recepcion: 'total', 'parcial' o 'sin_recepcion'\n"
            "  - superficie_construida_m2"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "MUNICIPALIDAD DE PROVIDENCIA — DIRECCIÓN DE OBRAS MUNICIPALES\n"
                    "CERTIFICADO DE RECEPCIÓN FINAL\n"
                    "Permiso de Edificación N° 234/2018\n"
                    "Recepción: TOTAL\n"
                    "Fecha de recepción: 15 de agosto de 2019\n"
                    "Superficie construida: 156,7 m²\n"
                    "Emitido: 30-04-2026"
                ),
                "extractions": [
                    {"extraction_class": "municipalidad", "extraction_text": "Providencia", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "30-04-2026", "attributes": {}},
                    {"extraction_class": "permiso_edificacion_n", "extraction_text": "234/2018", "attributes": {}},
                    {"extraction_class": "fecha_recepcion", "extraction_text": "15 de agosto de 2019", "attributes": {}},
                    {"extraction_class": "estado_recepcion", "extraction_text": "total", "attributes": {}},
                    {"extraction_class": "superficie_construida_m2", "extraction_text": "156,7", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "municipalidad": None, "fecha_emision": None,
            "permiso_edificacion_n": None, "fecha_recepcion": None,
            "estado_recepcion": None, "superficie_construida_m2": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "estado_recepcion":
                low = txt.lower().replace(" ", "_")
                if "total" in low:
                    out[cls] = "total"
                elif "parcial" in low:
                    out[cls] = "parcial"
                elif "sin" in low:
                    out[cls] = "sin_recepcion"
            elif cls == "superficie_construida_m2":
                try:
                    out[cls] = float(txt.replace(",", "."))
                except ValueError:
                    out[cls] = None
            else:
                out[cls] = txt
        return out
