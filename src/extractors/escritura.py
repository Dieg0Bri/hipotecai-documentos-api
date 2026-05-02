"""Extractor de escrituras públicas chilenas."""
from src.extractors.base import BaseExtractor


class EscrituraExtractor(BaseExtractor):
    tipo = "escritura"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave de esta escritura pública chilena. "
            "Identifica: tipo de acto (compraventa, hipoteca, alzamiento, herencia, "
            "donación), fecha de otorgamiento, notario y notaría, repertorio, foja, "
            "datos de la propiedad (rol, dirección, superficie, deslindes), partes "
            "(vendedores, compradores, hipotecante), precio en CLP y UF, y forma de pago. "
            "Cita el fragmento textual exacto del documento que respalda cada dato."
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "ESCRITURA PÚBLICA DE COMPRAVENTA. En Santiago, a 12 de marzo de 2022, "
                    "ante mí, JUAN PÉREZ GONZÁLEZ, Notario Público de la Cuarta Notaría de Santiago, "
                    "comparece doña MARÍA SOTO ROJAS, RUT 12.345.678-9, quien vende "
                    "a don PEDRO LÓPEZ, RUT 9.876.543-2, el inmueble ubicado en "
                    "Av. Apoquindo 5400, depto. 1404, comuna de Las Condes, Rol 12.345-7, "
                    "superficie 78,5 m². Precio: $145.000.000.-, equivalentes a UF 4.250."
                ),
                "extractions": [
                    {"extraction_class": "tipo_acto", "extraction_text": "compraventa", "attributes": {}},
                    {"extraction_class": "fecha_otorgamiento", "extraction_text": "12 de marzo de 2022", "attributes": {}},
                    {"extraction_class": "notario_nombre", "extraction_text": "JUAN PÉREZ GONZÁLEZ", "attributes": {}},
                    {"extraction_class": "notaria_numero", "extraction_text": "Cuarta Notaría de Santiago", "attributes": {}},
                    {"extraction_class": "vendedor", "extraction_text": "MARÍA SOTO ROJAS, RUT 12.345.678-9", "attributes": {}},
                    {"extraction_class": "comprador", "extraction_text": "PEDRO LÓPEZ, RUT 9.876.543-2", "attributes": {}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "direccion_propiedad", "extraction_text": "Av. Apoquindo 5400, depto. 1404, Las Condes", "attributes": {}},
                    {"extraction_class": "superficie_m2", "extraction_text": "78,5", "attributes": {}},
                    {"extraction_class": "precio_clp", "extraction_text": "145.000.000", "attributes": {}},
                    {"extraction_class": "precio_uf", "extraction_text": "4.250", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        result: dict = {
            "tipo_acto": None, "fecha_otorgamiento": None, "notario_nombre": None,
            "notaria_numero": None, "repertorio": None, "foja": None,
            "rol_propiedad": None, "direccion_propiedad": None, "superficie_m2": None,
            "deslindes": None, "vendedores": [], "compradores": [],
            "precio_clp": None, "precio_uf": None, "forma_pago": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()

            if cls == "vendedor":
                result["vendedores"].append(txt)
            elif cls == "comprador":
                result["compradores"].append(txt)
            elif cls in result:
                if cls in ("superficie_m2", "precio_uf"):
                    result[cls] = _parse_decimal(txt)
                elif cls == "precio_clp":
                    result[cls] = _parse_int(txt)
                else:
                    result[cls] = txt
        return result


def _parse_decimal(s: str) -> float | None:
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None
