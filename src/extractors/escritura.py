"""
Escritura pública (genérica).

Cubre el código legacy 'escritura' y comparte schema con escritura_compraventa
y escritura_anterior. El campo `tipo_acto` indica el tipo concreto.

Doc 3 §7 del spec del abogado: para tracto sucesivo (escrituras anteriores)
extraer foja, número, año del título y datos completos de comprador/vendedor.
"""
from src.extractors.base import BaseExtractor


class EscrituraExtractor(BaseExtractor):
    tipo = "escritura"

    def prompt(self) -> str:
        return (
            "Extrae los datos clave de esta escritura pública chilena (compraventa, hipoteca, "
            "alzamiento, donación, etc.):\n"
            "  - tipo_acto: clasifica como 'compraventa', 'hipoteca', 'alzamiento', "
            "'donacion', 'adjudicacion' u otro\n"
            "  - fecha_otorgamiento, notario_nombre, notaria_numero, repertorio\n"
            "  - foja, numero_inscripcion, anio_inscripcion, cbr_inscripcion (datos del CBR)\n"
            "  - vendedor_nombre + vendedor_rut + vendedor_estado_civil "
            "(casado/soltero/viudo/divorciado/conviviente_civil)\n"
            "  - vendedor_sociedad_conyugal_art150: si la vendedora compró 'casada en sociedad "
            "conyugal' invocando Patrimonio Reservado del Art. 150 (Sí/No)\n"
            "  - comprador_nombre + comprador_rut\n"
            "  - rol_propiedad, direccion_propiedad, superficie_m2\n"
            "  - deslindes (norte/sur/oriente/poniente, cada uno como deslinde_<dir>)\n"
            "  - precio_clp y/o precio_uf, forma_pago"
        )

    def examples(self) -> list[dict]:
        return [
            {
                "text": (
                    "ESCRITURA PÚBLICA DE COMPRAVENTA — Repertorio 2.345-2024.\n"
                    "En Santiago de Chile, a 30 de marzo de 2024, ante mí JUAN PÉREZ G., Notario Público "
                    "Titular de la 25ª Notaría de Santiago, comparecen:\n"
                    "Doña MARÍA SOTO LIRA, soltera, RUT 13.456.789-0, vende a\n"
                    "don LUIS RAMÍREZ TORO, casado en sociedad conyugal, RUT 14.567.890-1,\n"
                    "el inmueble Rol SII 12.345-7, ubicado en Av. Apoquindo 5400, Las Condes.\n"
                    "Inscripción CBR Las Condes: foja 1234 número 5678 año 2018.\n"
                    "Precio: UF 5.500, pagados al contado.\n"
                    "Deslindes: Norte: calle X; Sur: lote 12; Oriente: lote 8; Poniente: Av. Apoquindo."
                ),
                "extractions": [
                    {"extraction_class": "tipo_acto", "extraction_text": "compraventa", "attributes": {}},
                    {"extraction_class": "fecha_otorgamiento", "extraction_text": "30 de marzo de 2024", "attributes": {}},
                    {"extraction_class": "notario_nombre", "extraction_text": "JUAN PÉREZ G.", "attributes": {}},
                    {"extraction_class": "notaria_numero", "extraction_text": "25ª de Santiago", "attributes": {}},
                    {"extraction_class": "repertorio", "extraction_text": "2.345-2024", "attributes": {}},
                    {"extraction_class": "foja", "extraction_text": "1234", "attributes": {}},
                    {"extraction_class": "numero_inscripcion", "extraction_text": "5678", "attributes": {}},
                    {"extraction_class": "anio_inscripcion", "extraction_text": "2018", "attributes": {}},
                    {"extraction_class": "cbr_inscripcion", "extraction_text": "CBR Las Condes", "attributes": {}},
                    {"extraction_class": "vendedor_nombre", "extraction_text": "MARÍA SOTO LIRA", "attributes": {}},
                    {"extraction_class": "vendedor_rut", "extraction_text": "13.456.789-0", "attributes": {}},
                    {"extraction_class": "vendedor_estado_civil", "extraction_text": "soltero", "attributes": {}},
                    {"extraction_class": "comprador_nombre", "extraction_text": "LUIS RAMÍREZ TORO", "attributes": {}},
                    {"extraction_class": "comprador_rut", "extraction_text": "14.567.890-1", "attributes": {}},
                    {"extraction_class": "rol_propiedad", "extraction_text": "12.345-7", "attributes": {}},
                    {"extraction_class": "direccion_propiedad", "extraction_text": "Av. Apoquindo 5400, Las Condes", "attributes": {}},
                    {"extraction_class": "precio_uf", "extraction_text": "5.500", "attributes": {}},
                    {"extraction_class": "forma_pago", "extraction_text": "al contado", "attributes": {}},
                    {"extraction_class": "deslinde_norte", "extraction_text": "calle X", "attributes": {}},
                    {"extraction_class": "deslinde_sur", "extraction_text": "lote 12", "attributes": {}},
                    {"extraction_class": "deslinde_oriente", "extraction_text": "lote 8", "attributes": {}},
                    {"extraction_class": "deslinde_poniente", "extraction_text": "Av. Apoquindo", "attributes": {}},
                ],
            }
        ]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tipo_acto": None, "fecha_otorgamiento": None,
            "notario_nombre": None, "notaria_numero": None, "repertorio": None,
            "foja": None, "numero_inscripcion": None, "anio_inscripcion": None, "cbr_inscripcion": None,
            "vendedor_nombre": None, "vendedor_rut": None,
            "vendedor_estado_civil": None, "vendedor_sociedad_conyugal_art150": None,
            "comprador_nombre": None, "comprador_rut": None,
            "rol_propiedad": None, "direccion_propiedad": None, "superficie_m2": None,
            "deslindes": None,
            "precio_clp": None, "precio_uf": None, "forma_pago": None,
        }
        deslindes = {}
        for ex in lx_extractions:
            cls = getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)
            txt = getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls.startswith("deslinde_"):
                deslindes[cls.replace("deslinde_", "")] = txt
            elif cls == "anio_inscripcion":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "superficie_m2":
                try:
                    out[cls] = float(txt.replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls == "precio_clp":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "precio_uf":
                try:
                    out[cls] = float(txt.replace(".", "").replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls == "vendedor_sociedad_conyugal_art150":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            elif cls in out:
                out[cls] = txt
        if deslindes:
            out["deslindes"] = deslindes
        return out


# Aliases para los nuevos códigos del catálogo (mismo schema):
class EscrituraCompraventaExtractor(EscrituraExtractor):
    tipo = "escritura_compraventa"


class EscrituraAnteriorExtractor(EscrituraExtractor):
    """Tracto sucesivo (10 años). Mismo schema; el clasificador distingue por contexto."""
    tipo = "escritura_anterior"
