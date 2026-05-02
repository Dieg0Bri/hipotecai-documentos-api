"""
Certificado de Deuda de Contribuciones (TGR).
Doc 3 §9 del spec del abogado.
"""
from src.extractors.base import BaseExtractor


class CertDeudaContribucionesExtractor(BaseExtractor):
    tipo = "cert_deuda_contribuciones"

    def prompt(self) -> str:
        return (
            "Extrae los datos de este Certificado de Deuda de Contribuciones de la "
            "Tesorería General de la República (TGR) de Chile:\n"
            "  - rol_propiedad y comuna\n"
            "  - fecha_emision\n"
            "  - estado_deuda: 'no_registra_deuda' si dice que no hay deuda; "
            "'registra_deuda' si registra deuda morosa\n"
            "  - monto_total_moroso_clp: monto total adeudado (solo si registra deuda)\n"
            "  - cuotas_pendientes: cantidad de cuotas pendientes (si lo dice)"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "TESORERÍA GENERAL DE LA REPÚBLICA\n"
                    "Certificado de Deuda de Contribuciones\n"
                    "Rol: 12.345-7  Comuna: Las Condes\n"
                    "Estado: NO REGISTRA DEUDA pendiente al 30-04-2026."
                ),
                "extractions": [
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "comuna", "extraction_text": "Las Condes", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "30-04-2026", "attributes": {}},
                    {"extraction_class": "estado_deuda", "extraction_text": "no_registra_deuda", "attributes": {}},
                ],
            },
            {
                "text": (
                    "TGR — Certificado de Deuda de Contribuciones\n"
                    "Rol: 99.876-5  Comuna: Maipú  Emitido: 12-03-2026\n"
                    "REGISTRA DEUDA. Monto total adeudado: $ 432.500. Cuotas pendientes: 3."
                ),
                "extractions": [
                    {"extraction_class": "rol_propiedad", "extraction_text": "99.876-5", "attributes": {}},
                    {"extraction_class": "comuna", "extraction_text": "Maipú", "attributes": {}},
                    {"extraction_class": "fecha_emision", "extraction_text": "12-03-2026", "attributes": {}},
                    {"extraction_class": "estado_deuda", "extraction_text": "registra_deuda", "attributes": {}},
                    {"extraction_class": "monto_total_moroso_clp", "extraction_text": "432.500", "attributes": {}},
                    {"extraction_class": "cuotas_pendientes", "extraction_text": "3", "attributes": {}},
                ],
            },
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "rol_propiedad": None, "comuna": None, "fecha_emision": None,
            "estado_deuda": None, "monto_total_moroso_clp": None, "cuotas_pendientes": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "monto_total_moroso_clp":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "cuotas_pendientes":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "estado_deuda":
                low = txt.lower().replace(" ", "_")
                if "no" in low and "deuda" in low:
                    out[cls] = "no_registra_deuda"
                elif "deuda" in low:
                    out[cls] = "registra_deuda"
            else:
                out[cls] = txt
        return out
