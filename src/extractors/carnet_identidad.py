"""
Carnet de Identidad chileno.
Doc 3 §1 del spec del abogado: RUT (con validación), nombre, nacionalidad,
profesión, estado civil declarado.
"""
from src.extractors.base import BaseExtractor


class CarnetIdentidadExtractor(BaseExtractor):
    tipo = "carnet_identidad"

    def prompt(self) -> str:
        return (
            "Extrae los datos de esta cédula de identidad chilena:\n"
            "  - rut: con guión y dígito verificador (formato 12.345.678-K)\n"
            "  - nombre_completo: nombres + apellido paterno + apellido materno\n"
            "  - nacionalidad: nacionalidad declarada\n"
            "  - profesion_oficio: profesión u oficio (puede no aparecer)\n"
            "  - estado_civil_declarado: una de [soltero, casado, viudo, divorciado, "
            "conviviente_civil] — el carnet chileno NO suele declararlo, devuelve solo si está\n"
            "  - fecha_nacimiento: en formato ISO YYYY-MM-DD si es posible"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "REPÚBLICA DE CHILE — SERVICIO DE REGISTRO CIVIL E IDENTIFICACIÓN\n"
                    "CÉDULA DE IDENTIDAD\n"
                    "RUN: 14.567.890-1\n"
                    "Nombres: LUIS ALBERTO\n"
                    "Apellidos: RAMÍREZ TORO\n"
                    "Nacionalidad: CHILENA\n"
                    "Fecha de nacimiento: 12/05/1985\n"
                    "Profesión: Ingeniero Civil"
                ),
                "extractions": [
                    {"extraction_class": "rut", "extraction_text": "14.567.890-1", "attributes": {}},
                    {"extraction_class": "nombre_completo", "extraction_text": "LUIS ALBERTO RAMÍREZ TORO", "attributes": {}},
                    {"extraction_class": "nacionalidad", "extraction_text": "CHILENA", "attributes": {}},
                    {"extraction_class": "profesion_oficio", "extraction_text": "Ingeniero Civil", "attributes": {}},
                    {"extraction_class": "fecha_nacimiento", "extraction_text": "1985-05-12", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "rut": None, "rut_valido": None,
            "nombre_completo": None, "nacionalidad": None,
            "profesion_oficio": None, "estado_civil_declarado": None,
            "fecha_nacimiento": None,
        }
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None or cls not in out:
                continue
            out[cls] = str(txt).strip()

        if out["rut"]:
            out["rut_valido"] = _validar_rut_chileno(out["rut"])
        return out


def _validar_rut_chileno(rut: str) -> bool:
    """Valida el dígito verificador del RUT chileno (módulo 11)."""
    rut = rut.replace(".", "").replace(" ", "").upper()
    if "-" not in rut:
        return False
    cuerpo, dv = rut.split("-")
    if not cuerpo.isdigit() or len(dv) != 1:
        return False
    dv = "K" if dv == "K" else dv
    multiplicador = 2
    suma = 0
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        dv_esperado = "0"
    elif resto == 10:
        dv_esperado = "K"
    else:
        dv_esperado = str(resto)
    return dv == dv_esperado
