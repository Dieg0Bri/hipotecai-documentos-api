"""
Extractores para tipos condicionales del catálogo (los que se piden cuando un
trigger detecta una condición especial). Agrupados aquí para reducir boilerplate.

Cubre:
  · Persona jurídica:   e_rut_sii, escritura_constitucion_social, cert_vigencia_poderes
  · Condominio:         cert_deuda_gastos_comunes, acta_asamblea_copropietarios
  · Subsidio SERVIU:    resolucion_serviu
  · Tribunales:         sentencia_judicial, cert_ejecutoria
  · Rural / SAG:        cert_subdivision_sag
  · Indígena:           cert_conadi
  · Herencia:           cert_posesion_efectiva, cert_exencion_herencia_sii
  · Escrituras esp.:    escritura_alzamiento_hipoteca, escritura_bien_familiar,
                        escritura_renuncia_usufructo
"""
from src.extractors.base import BaseExtractor


# ─────────────────────────── PERSONA JURÍDICA ─────────────────────────────


class ERutSiiExtractor(BaseExtractor):
    tipo = "e_rut_sii"

    def prompt(self) -> str:
        return (
            "Extrae datos del e-RUT (RUT electrónico) emitido por el SII chileno:\n"
            "  - rut_sociedad, razon_social, fecha_emision, actividad_economica"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "SERVICIO DE IMPUESTOS INTERNOS — Cédula RUT\n"
                "Razón Social: HIPOTECAI SpA\nRUT: 76.123.456-K\n"
                "Actividad: Servicios profesionales jurídicos\n"
                "Emitido: 10-01-2024"
            ),
            "extractions": [
                {"extraction_class": "rut_sociedad", "extraction_text": "76.123.456-K", "attributes": {}},
                {"extraction_class": "razon_social", "extraction_text": "HIPOTECAI SpA", "attributes": {}},
                {"extraction_class": "actividad_economica", "extraction_text": "Servicios profesionales jurídicos", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "10-01-2024", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        return _simple_parse(lx_extractions, ["rut_sociedad", "razon_social", "fecha_emision", "actividad_economica"])


class EscrituraConstitucionSocialExtractor(BaseExtractor):
    tipo = "escritura_constitucion_social"

    def prompt(self) -> str:
        return (
            "Extrae datos de la Escritura de Constitución de Sociedad chilena:\n"
            "  - fecha_otorgamiento, notario_nombre\n"
            "  - razon_social, rut_sociedad, tipo_sociedad (spa/sa/ltda/eirl)\n"
            "  - capital_clp\n"
            "  - origen: 'res_empresa_dia' (Tu Empresa en un Día) o 'tradicional_cbr'\n"
            "  - socio: por cada socio (nombre + rut + porcentaje)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "ESCRITURA PÚBLICA DE CONSTITUCIÓN DE SOCIEDAD\n"
                "Notario Juan Pérez, 5 de marzo de 2024.\n"
                "Constitúyese una sociedad por acciones bajo razón social HIPOTECAI SpA, "
                "RUT en trámite. Capital: $ 10.000.000. Socios: Diego Cabezas (50%) y María Pérez (50%).\n"
                "Inscrita en el Registro de Empresas y Sociedades."
            ),
            "extractions": [
                {"extraction_class": "fecha_otorgamiento", "extraction_text": "5 de marzo de 2024", "attributes": {}},
                {"extraction_class": "notario_nombre", "extraction_text": "Juan Pérez", "attributes": {}},
                {"extraction_class": "razon_social", "extraction_text": "HIPOTECAI SpA", "attributes": {}},
                {"extraction_class": "tipo_sociedad", "extraction_text": "spa", "attributes": {}},
                {"extraction_class": "capital_clp", "extraction_text": "10.000.000", "attributes": {}},
                {"extraction_class": "origen", "extraction_text": "res_empresa_dia", "attributes": {}},
                {"extraction_class": "socio", "extraction_text": "Diego Cabezas", "attributes": {"porcentaje": "50"}},
                {"extraction_class": "socio", "extraction_text": "María Pérez", "attributes": {"porcentaje": "50"}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "fecha_otorgamiento": None, "notario_nombre": None,
            "razon_social": None, "rut_sociedad": None, "tipo_sociedad": None,
            "capital_clp": None, "origen": None,
            "socios": [],
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex); attrs = _attrs(ex)
            if not cls or txt is None:
                continue
            if cls == "socio":
                out["socios"].append({"nombre": str(txt).strip(), "porcentaje": attrs.get("porcentaje")})
            elif cls == "capital_clp":
                digits = "".join(c for c in str(txt) if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls in out:
                out[cls] = str(txt).strip()
        return out


class CertVigenciaPoderesExtractor(BaseExtractor):
    tipo = "cert_vigencia_poderes"

    def prompt(self) -> str:
        return (
            "Extrae datos del Certificado de Vigencia de Poderes (Conservador de Comercio o "
            "portal Tu Empresa en un Día / RES):\n"
            "  - razon_social, rut_sociedad, fecha_emision (debe ser < 30 días para validez)\n"
            "  - representante: por cada representante con sus facultades\n"
            "    (atributos: facultades = 'comprar', 'vender', 'enajenar', 'hipotecar', 'dar_garantia')\n"
            "  - condiciones_poder: 'actuacion_conjunta', 'individual', 'directorio' o 'junta_accionistas'\n"
            "  - limite_uf y/o limite_clp si el poder tiene tope monetario"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "CONSERVADOR DE COMERCIO — Vigencia de Poderes\n"
                "Sociedad: INVERSIONES TORRES SpA, RUT 76.555.444-3\n"
                "Emitido: 25-04-2026\n"
                "Representantes habilitados:\n"
                "1) PEDRO TORRES, RUT 12.345.678-9 — facultades: comprar, vender, hipotecar.\n"
                "2) ANA RÍOS, RUT 13.456.789-0 — facultades: vender, enajenar.\n"
                "Modalidad: actuación CONJUNTA. Tope: UF 5.000."
            ),
            "extractions": [
                {"extraction_class": "razon_social", "extraction_text": "INVERSIONES TORRES SpA", "attributes": {}},
                {"extraction_class": "rut_sociedad", "extraction_text": "76.555.444-3", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "25-04-2026", "attributes": {}},
                {"extraction_class": "representante", "extraction_text": "PEDRO TORRES",
                 "attributes": {"rut": "12.345.678-9", "facultades": "comprar,vender,hipotecar"}},
                {"extraction_class": "representante", "extraction_text": "ANA RÍOS",
                 "attributes": {"rut": "13.456.789-0", "facultades": "vender,enajenar"}},
                {"extraction_class": "condiciones_poder", "extraction_text": "actuacion_conjunta", "attributes": {}},
                {"extraction_class": "limite_uf", "extraction_text": "5.000", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "razon_social": None, "rut_sociedad": None, "fecha_emision": None,
            "representantes": [], "condiciones_poder": None,
            "limite_uf": None, "limite_clp": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex); attrs = _attrs(ex)
            if not cls or txt is None:
                continue
            if cls == "representante":
                facs = attrs.get("facultades", "")
                facs_list = [f.strip() for f in str(facs).split(",") if f.strip()]
                out["representantes"].append({
                    "nombre": str(txt).strip(),
                    "rut": attrs.get("rut"),
                    "facultades": facs_list,
                })
            elif cls == "limite_uf":
                try:
                    out[cls] = float(str(txt).replace(".", "").replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls == "limite_clp":
                digits = "".join(c for c in str(txt) if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls in out:
                out[cls] = str(txt).strip()
        return out


# ─────────────────────────── CONDOMINIO ───────────────────────────────────


class CertDeudaGastosComunesExtractor(BaseExtractor):
    tipo = "cert_deuda_gastos_comunes"

    def prompt(self) -> str:
        return (
            "Extrae datos del Certificado de Deuda de Gastos Comunes emitido por la "
            "administración del condominio:\n"
            "  - fecha_emision\n"
            "  - administrador_nombre, administrador_rut\n"
            "  - emisor: 'administrador_profesional' o 'presidente_comite'\n"
            "  - monto_deuda_clp, cuotas_pendientes\n"
            "  - inscripcion_reglamento_*: foja, numero, anio, cbr (del reglamento de copropiedad)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "Comunidad Edificio Apoquindo. Administrador: Asesorías Vega Ltda, RUT 76.111.222-3.\n"
                "Certifica que el dpto. 1404 mantiene una deuda de gastos comunes de $ 350.000 "
                "(2 cuotas pendientes). Reglamento de Copropiedad inscrito a fojas 3.500 N° 7.200 "
                "año 2010, CBR Las Condes. Emitido: 28-04-2026."
            ),
            "extractions": [
                {"extraction_class": "administrador_nombre", "extraction_text": "Asesorías Vega Ltda", "attributes": {}},
                {"extraction_class": "administrador_rut", "extraction_text": "76.111.222-3", "attributes": {}},
                {"extraction_class": "emisor", "extraction_text": "administrador_profesional", "attributes": {}},
                {"extraction_class": "monto_deuda_clp", "extraction_text": "350.000", "attributes": {}},
                {"extraction_class": "cuotas_pendientes", "extraction_text": "2", "attributes": {}},
                {"extraction_class": "inscripcion_reglamento_foja", "extraction_text": "3.500", "attributes": {}},
                {"extraction_class": "inscripcion_reglamento_numero", "extraction_text": "7.200", "attributes": {}},
                {"extraction_class": "inscripcion_reglamento_anio", "extraction_text": "2010", "attributes": {}},
                {"extraction_class": "inscripcion_reglamento_cbr", "extraction_text": "CBR Las Condes", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "28-04-2026", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "fecha_emision": None,
            "administrador_nombre": None, "administrador_rut": None,
            "emisor": None,
            "monto_deuda_clp": None, "cuotas_pendientes": None,
            "inscripcion_reglamento": None,
        }
        insc = {}
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls.startswith("inscripcion_reglamento_"):
                key = cls.replace("inscripcion_reglamento_", "")
                if key == "anio":
                    digits = "".join(c for c in txt if c.isdigit())
                    insc["anio"] = int(digits) if digits else None
                else:
                    insc[key] = txt
            elif cls == "monto_deuda_clp":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "cuotas_pendientes":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls in out:
                out[cls] = txt
        if insc:
            out["inscripcion_reglamento"] = insc
        return out


class ActaAsambleaCopropietariosExtractor(BaseExtractor):
    tipo = "acta_asamblea_copropietarios"

    def prompt(self) -> str:
        return (
            "Extrae del Acta de Asamblea de Copropietarios (reducida a escritura pública):\n"
            "  - fecha_asamblea, notaria\n"
            "  - administrador_nombrado / presidente_comite_nombrado\n"
            "  - foja_inscripcion, numero_inscripcion, anio_inscripcion (CBR)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "Acta de asamblea ordinaria del Edificio Apoquindo, celebrada el 15-03-2026, "
                "reducida a escritura pública en Notaría Juan Pérez. Se nombra administrador a "
                "Asesorías Vega Ltda. Inscrita a fojas 5.000 N° 9.000 año 2026, CBR Las Condes."
            ),
            "extractions": [
                {"extraction_class": "fecha_asamblea", "extraction_text": "15-03-2026", "attributes": {}},
                {"extraction_class": "notaria", "extraction_text": "Notaría Juan Pérez", "attributes": {}},
                {"extraction_class": "administrador_nombrado", "extraction_text": "Asesorías Vega Ltda", "attributes": {}},
                {"extraction_class": "foja_inscripcion", "extraction_text": "5.000", "attributes": {}},
                {"extraction_class": "numero_inscripcion", "extraction_text": "9.000", "attributes": {}},
                {"extraction_class": "anio_inscripcion", "extraction_text": "2026", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "fecha_asamblea": None, "notaria": None,
            "administrador_nombrado": None, "presidente_comite_nombrado": None,
            "foja_inscripcion": None, "numero_inscripcion": None, "anio_inscripcion": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "anio_inscripcion":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            else:
                out[cls] = txt
        return out


# ─────────────────────────── SERVIU ───────────────────────────────────────


class ResolucionServiuExtractor(BaseExtractor):
    tipo = "resolucion_serviu"

    def prompt(self) -> str:
        return (
            "Extrae datos de la Resolución del SERVIU (subsidio habitacional):\n"
            "  - numero_resolucion, fecha_emision\n"
            "  - plazo_prohibicion_anios: 5, 10 o 15\n"
            "  - fecha_vencimiento_prohibicion (calculada o explícita)\n"
            "  - autoriza_venta_anticipada (sí/no)\n"
            "  - alza_prohibicion (sí/no — alzamiento definitivo)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "SERVIU REGIÓN METROPOLITANA — Resolución Exenta N° 2.345 del 10-04-2026.\n"
                "Autoriza venta anticipada del inmueble Rol 12.345-7, por haber cumplido el plazo "
                "legal de 5 años contado desde la inscripción (vence: 10-04-2026). "
                "Alza la prohibición a favor del SERVIU."
            ),
            "extractions": [
                {"extraction_class": "numero_resolucion", "extraction_text": "2.345", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "10-04-2026", "attributes": {}},
                {"extraction_class": "plazo_prohibicion_anios", "extraction_text": "5", "attributes": {}},
                {"extraction_class": "fecha_vencimiento_prohibicion", "extraction_text": "10-04-2026", "attributes": {}},
                {"extraction_class": "autoriza_venta_anticipada", "extraction_text": "sí", "attributes": {}},
                {"extraction_class": "alza_prohibicion", "extraction_text": "sí", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "numero_resolucion": None, "fecha_emision": None,
            "plazo_prohibicion_anios": None, "fecha_vencimiento_prohibicion": None,
            "autoriza_venta_anticipada": None, "alza_prohibicion": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "plazo_prohibicion_anios":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls in ("autoriza_venta_anticipada", "alza_prohibicion"):
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out


# ─────────────────────────── TRIBUNALES ───────────────────────────────────


class SentenciaJudicialExtractor(BaseExtractor):
    tipo = "sentencia_judicial"

    def prompt(self) -> str:
        return (
            "Extrae datos de la sentencia judicial chilena (típicamente Tribunal de Familia):\n"
            "  - tribunal: nombre completo (ej. '1° Juzgado de Familia de Santiago')\n"
            "  - causa_rit_rol: en formato C-XXXX-YYYY o RIT-XXXXX-YYYY\n"
            "  - fecha_resolucion\n"
            "  - menor_nombre, menor_rut (si aplica)\n"
            "  - tipo_autorizacion: 'venta_publica_subasta', 'venta_directa' o 'venta_con_retencion'\n"
            "  - ejecutoriada: sí/no (la sentencia debe estar firme — REQUISITO BLOQUEANTE)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "1° JUZGADO DE FAMILIA DE SANTIAGO\n"
                "Causa RIT C-1234-2023. Fecha: 15 de septiembre de 2024.\n"
                "Resuélvese: autorizar la venta directa del inmueble Rol 12.345-7 perteneciente "
                "al menor JUAN PEDRO ROJAS LIRA, RUT 25.678.901-2.\n"
                "La presente sentencia se encuentra ejecutoriada."
            ),
            "extractions": [
                {"extraction_class": "tribunal", "extraction_text": "1° Juzgado de Familia de Santiago", "attributes": {}},
                {"extraction_class": "causa_rit_rol", "extraction_text": "C-1234-2023", "attributes": {}},
                {"extraction_class": "fecha_resolucion", "extraction_text": "15 de septiembre de 2024", "attributes": {}},
                {"extraction_class": "menor_nombre", "extraction_text": "JUAN PEDRO ROJAS LIRA", "attributes": {}},
                {"extraction_class": "menor_rut", "extraction_text": "25.678.901-2", "attributes": {}},
                {"extraction_class": "tipo_autorizacion", "extraction_text": "venta_directa", "attributes": {}},
                {"extraction_class": "ejecutoriada", "extraction_text": "sí", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tribunal": None, "causa_rit_rol": None, "fecha_resolucion": None,
            "menor_nombre": None, "menor_rut": None,
            "tipo_autorizacion": None, "ejecutoriada": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "ejecutoriada":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out


class CertEjecutoriaExtractor(BaseExtractor):
    tipo = "cert_ejecutoria"

    def prompt(self) -> str:
        return (
            "Extrae del Certificado de Ejecutoria (sentencia firme):\n"
            "  - tribunal, causa_rit_rol, fecha_emision\n"
            "  - sentencia_firme: sí/no"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "PODER JUDICIAL — Certificado de Ejecutoria. Causa C-1234-2023, "
                "1° Juzgado de Familia de Santiago. Se certifica que la sentencia se encuentra "
                "EJECUTORIADA y firme. Emitido: 20-10-2024."
            ),
            "extractions": [
                {"extraction_class": "tribunal", "extraction_text": "1° Juzgado de Familia de Santiago", "attributes": {}},
                {"extraction_class": "causa_rit_rol", "extraction_text": "C-1234-2023", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "20-10-2024", "attributes": {}},
                {"extraction_class": "sentencia_firme", "extraction_text": "sí", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {"tribunal": None, "causa_rit_rol": None, "fecha_emision": None, "sentencia_firme": None}
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            out[cls] = (txt.lower() in ("sí", "si", "true", "1")) if cls == "sentencia_firme" else txt
        return out


# ─────────────────────────── RURAL / SAG ──────────────────────────────────


class CertSubdivisionSagExtractor(BaseExtractor):
    tipo = "cert_subdivision_sag"

    def prompt(self) -> str:
        return (
            "Extrae del Certificado de Subdivisión SAG (parcelas D.L. 3.516):\n"
            "  - numero_resolucion, fecha_aprobacion\n"
            "  - superficie_predial_m2 (debe ser >= 5000 para ser legal)\n"
            "  - plano_archivado_*: numero, anio, cbr donde está archivado el plano\n"
            "  - prohibicion_uso_urbano_comercial: si la escritura prohíbe destino urbano/comercial"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "SERVICIO AGRÍCOLA Y GANADERO — Resolución 234/2018 del 12-06-2018.\n"
                "Aprueba subdivisión predial. Lote N°7, superficie 5.200 m². Plano archivado "
                "bajo número 1234, año 2018, CBR Talagante. Se prohíbe destino urbano o comercial."
            ),
            "extractions": [
                {"extraction_class": "numero_resolucion", "extraction_text": "234/2018", "attributes": {}},
                {"extraction_class": "fecha_aprobacion", "extraction_text": "12-06-2018", "attributes": {}},
                {"extraction_class": "superficie_predial_m2", "extraction_text": "5.200", "attributes": {}},
                {"extraction_class": "plano_archivado_numero", "extraction_text": "1234", "attributes": {}},
                {"extraction_class": "plano_archivado_anio", "extraction_text": "2018", "attributes": {}},
                {"extraction_class": "plano_archivado_cbr", "extraction_text": "CBR Talagante", "attributes": {}},
                {"extraction_class": "prohibicion_uso_urbano_comercial", "extraction_text": "sí", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "numero_resolucion": None, "fecha_aprobacion": None,
            "superficie_predial_m2": None, "cumple_minimo_legal": None,
            "plano_archivado": None, "prohibicion_uso_urbano_comercial": None,
        }
        plano = {}
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls.startswith("plano_archivado_"):
                key = cls.replace("plano_archivado_", "")
                if key == "anio":
                    digits = "".join(c for c in txt if c.isdigit())
                    plano["anio"] = int(digits) if digits else None
                else:
                    plano[key] = txt
            elif cls == "superficie_predial_m2":
                try:
                    out[cls] = float(txt.replace(".", "").replace(",", "."))
                except ValueError:
                    out[cls] = None
            elif cls == "prohibicion_uso_urbano_comercial":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            elif cls in out:
                out[cls] = txt
        if plano:
            out["plano_archivado"] = plano
        if out["superficie_predial_m2"] is not None:
            out["cumple_minimo_legal"] = out["superficie_predial_m2"] >= 5000
        return out


class PlanoSubdivisionSagExtractor(CertSubdivisionSagExtractor):
    """Plano archivado del SAG. Mismo schema que el certificado de subdivisión."""
    tipo = "plano_subdivision_sag"


# ─────────────────────────── INDÍGENA / CONADI ────────────────────────────


class CertConadiExtractor(BaseExtractor):
    tipo = "cert_conadi"

    def prompt(self) -> str:
        return (
            "Extrae del Certificado CONADI (Ley 19.253):\n"
            "  - numero_resolucion, fecha_emision\n"
            "  - persona_nombre + persona_rut\n"
            "  - rol: 'vendedor' o 'comprador' (a quién acredita)\n"
            "  - calidad_indigena_acreditada: sí/no\n"
            "  - etnia: mapuche, aymara, atacameña, etc."
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "CORPORACIÓN NACIONAL DE DESARROLLO INDÍGENA — CONADI\n"
                "Resolución 567/2026 del 15-03-2026. Acredita la calidad indígena MAPUCHE de "
                "JOSÉ ANTILEF MILLARAY, RUT 18.234.567-8, en su condición de COMPRADOR."
            ),
            "extractions": [
                {"extraction_class": "numero_resolucion", "extraction_text": "567/2026", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "15-03-2026", "attributes": {}},
                {"extraction_class": "persona_nombre", "extraction_text": "JOSÉ ANTILEF MILLARAY", "attributes": {}},
                {"extraction_class": "persona_rut", "extraction_text": "18.234.567-8", "attributes": {}},
                {"extraction_class": "rol", "extraction_text": "comprador", "attributes": {}},
                {"extraction_class": "calidad_indigena_acreditada", "extraction_text": "sí", "attributes": {}},
                {"extraction_class": "etnia", "extraction_text": "mapuche", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "numero_resolucion": None, "fecha_emision": None,
            "persona_nombre": None, "persona_rut": None,
            "rol": None, "calidad_indigena_acreditada": None, "etnia": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "calidad_indigena_acreditada":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out


# ─────────────────────────── HERENCIA ─────────────────────────────────────


class CertPosesionEfectivaExtractor(BaseExtractor):
    tipo = "cert_posesion_efectiva"

    def prompt(self) -> str:
        return (
            "Extrae del Auto/Resolución de Posesión Efectiva chilena:\n"
            "  - organismo: 'registro_civil' (intestada moderna) o 'tribunal' (testada/antigua)\n"
            "  - numero_resolucion, fecha_resolucion\n"
            "  - causante_nombre + causante_rut\n"
            "  - fecha_defuncion\n"
            "  - heredero: por cada heredero (nombre + rut + grado de parentesco)\n"
            "  - inscripcion_especial_*: foja, numero, anio, cbr de la inscripción especial de herencia"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "REGISTRO CIVIL — Resolución 12.345 del 10-02-2024.\n"
                "Concede posesión efectiva intestada de los bienes quedados al fallecimiento de "
                "JUAN ROJAS LIRA, RUT 5.555.555-5, fallecido el 22-12-2023, a sus herederos: "
                "PEDRO ROJAS PÉREZ (hijo), RUT 18.888.888-8 y ANA ROJAS PÉREZ (hija), RUT 19.999.999-9.\n"
                "Inscripción Especial de Herencia: foja 1.000 N° 2.000 año 2024, CBR Santiago."
            ),
            "extractions": [
                {"extraction_class": "organismo", "extraction_text": "registro_civil", "attributes": {}},
                {"extraction_class": "numero_resolucion", "extraction_text": "12.345", "attributes": {}},
                {"extraction_class": "fecha_resolucion", "extraction_text": "10-02-2024", "attributes": {}},
                {"extraction_class": "causante_nombre", "extraction_text": "JUAN ROJAS LIRA", "attributes": {}},
                {"extraction_class": "causante_rut", "extraction_text": "5.555.555-5", "attributes": {}},
                {"extraction_class": "fecha_defuncion", "extraction_text": "22-12-2023", "attributes": {}},
                {"extraction_class": "heredero", "extraction_text": "PEDRO ROJAS PÉREZ",
                 "attributes": {"rut": "18.888.888-8", "parentesco": "hijo"}},
                {"extraction_class": "heredero", "extraction_text": "ANA ROJAS PÉREZ",
                 "attributes": {"rut": "19.999.999-9", "parentesco": "hija"}},
                {"extraction_class": "inscripcion_especial_foja", "extraction_text": "1.000", "attributes": {}},
                {"extraction_class": "inscripcion_especial_numero", "extraction_text": "2.000", "attributes": {}},
                {"extraction_class": "inscripcion_especial_anio", "extraction_text": "2024", "attributes": {}},
                {"extraction_class": "inscripcion_especial_cbr", "extraction_text": "CBR Santiago", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "organismo": None, "numero_resolucion": None, "fecha_resolucion": None,
            "causante_nombre": None, "causante_rut": None, "fecha_defuncion": None,
            "herederos": [], "inscripcion_especial_herencia": None,
        }
        insc = {}
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex); attrs = _attrs(ex)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls == "heredero":
                out["herederos"].append({
                    "nombre": txt, "rut": attrs.get("rut"), "parentesco": attrs.get("parentesco"),
                })
            elif cls.startswith("inscripcion_especial_"):
                key = cls.replace("inscripcion_especial_", "")
                if key == "anio":
                    digits = "".join(c for c in txt if c.isdigit())
                    insc["anio"] = int(digits) if digits else None
                else:
                    insc[key] = txt
            elif cls in out:
                out[cls] = txt
        if insc:
            out["inscripcion_especial_herencia"] = insc
        return out


class CertExencionHerenciaSiiExtractor(BaseExtractor):
    tipo = "cert_exencion_herencia_sii"

    def prompt(self) -> str:
        return (
            "Extrae del Certificado SII de Impuesto a las Herencias:\n"
            "  - numero_resolucion, fecha_emision\n"
            "  - causante_nombre + causante_rut\n"
            "  - estado: 'exento' o 'pagado'\n"
            "  - monto_pagado_clp (si aplica)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "SERVICIO DE IMPUESTOS INTERNOS — Certificado N° 8.901/2024 del 30-03-2024.\n"
                "Causante: JUAN ROJAS LIRA, RUT 5.555.555-5. Estado: EXENTO de impuesto a las herencias."
            ),
            "extractions": [
                {"extraction_class": "numero_resolucion", "extraction_text": "8.901/2024", "attributes": {}},
                {"extraction_class": "fecha_emision", "extraction_text": "30-03-2024", "attributes": {}},
                {"extraction_class": "causante_nombre", "extraction_text": "JUAN ROJAS LIRA", "attributes": {}},
                {"extraction_class": "causante_rut", "extraction_text": "5.555.555-5", "attributes": {}},
                {"extraction_class": "estado", "extraction_text": "exento", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "numero_resolucion": None, "fecha_emision": None,
            "causante_nombre": None, "causante_rut": None,
            "estado": None, "monto_pagado_clp": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "monto_pagado_clp":
                digits = "".join(c for c in txt if c.isdigit())
                out[cls] = int(digits) if digits else None
            elif cls == "estado":
                out[cls] = "pagado" if "pag" in txt.lower() else ("exento" if "exent" in txt.lower() else txt)
            else:
                out[cls] = txt
        return out


# ─────────────────────────── ESCRITURAS CONDICIONALES ─────────────────────


class EscrituraAlzamientoHipotecaExtractor(BaseExtractor):
    tipo = "escritura_alzamiento_hipoteca"

    def prompt(self) -> str:
        return (
            "Extrae datos de la escritura pública donde un banco alza/cancela una hipoteca:\n"
            "  - fecha_otorgamiento, notario_nombre, notaria_numero\n"
            "  - institucion_acreedor: razón social del banco\n"
            "  - institucion_rut\n"
            "  - hipoteca_alzada_*: foja, numero, anio, fecha_inscripcion (de la hipoteca original)\n"
            "  - representante_banco: nombre + rut + foja_personeria + notaria_personeria + fecha_personeria"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "ESCRITURA PÚBLICA DE ALZAMIENTO HIPOTECARIO. Notaría 25 Santiago, notario Juan Pérez. "
                "5 de mayo de 2026. BANCO BICE S.A., RUT 97.080.000-K, representado por don PEDRO LIRA, "
                "RUT 12.345.678-9, conforme a personería de fojas 100 N° 200 de Notaría 1 Santiago, "
                "30-01-2020. Alza la hipoteca inscrita a fojas 4321 N° 8765 año 2020 CBR Santiago."
            ),
            "extractions": [
                {"extraction_class": "fecha_otorgamiento", "extraction_text": "5 de mayo de 2026", "attributes": {}},
                {"extraction_class": "notario_nombre", "extraction_text": "Juan Pérez", "attributes": {}},
                {"extraction_class": "notaria_numero", "extraction_text": "25 Santiago", "attributes": {}},
                {"extraction_class": "institucion_acreedor", "extraction_text": "BANCO BICE S.A.", "attributes": {}},
                {"extraction_class": "institucion_rut", "extraction_text": "97.080.000-K", "attributes": {}},
                {"extraction_class": "hipoteca_alzada_foja", "extraction_text": "4321", "attributes": {}},
                {"extraction_class": "hipoteca_alzada_numero", "extraction_text": "8765", "attributes": {}},
                {"extraction_class": "hipoteca_alzada_anio", "extraction_text": "2020", "attributes": {}},
                {"extraction_class": "representante_banco", "extraction_text": "PEDRO LIRA",
                 "attributes": {"rut": "12.345.678-9",
                                "foja_personeria": "100",
                                "notaria_personeria": "Notaría 1 Santiago",
                                "fecha_personeria": "30-01-2020"}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "fecha_otorgamiento": None, "notario_nombre": None, "notaria_numero": None,
            "institucion_acreedor": None, "institucion_rut": None,
            "hipoteca_alzada": None,
            "representantes_banco": [],
        }
        hip = {}
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex); attrs = _attrs(ex)
            if not cls or txt is None:
                continue
            txt = str(txt).strip()
            if cls == "representante_banco":
                out["representantes_banco"].append({
                    "nombre": txt,
                    "rut": attrs.get("rut"),
                    "foja_personeria": attrs.get("foja_personeria"),
                    "notaria_personeria": attrs.get("notaria_personeria"),
                    "fecha_personeria": attrs.get("fecha_personeria"),
                })
            elif cls.startswith("hipoteca_alzada_"):
                key = cls.replace("hipoteca_alzada_", "")
                if key == "anio":
                    digits = "".join(c for c in txt if c.isdigit())
                    hip["anio"] = int(digits) if digits else None
                else:
                    hip[key] = txt
            elif cls in out:
                out[cls] = txt
        if hip:
            out["hipoteca_alzada"] = hip
        return out


class EscrituraBienFamiliarExtractor(BaseExtractor):
    tipo = "escritura_bien_familiar"

    def prompt(self) -> str:
        return (
            "Extrae datos de la escritura sobre Bien Familiar:\n"
            "  - tipo_documento: 'escritura_desafectacion', 'autorizacion_conyuge' o 'sentencia_judicial'\n"
            "  - notaria_o_tribunal, fecha_documento\n"
            "  - conyuge_nombre + conyuge_rut\n"
            "  - consta_subinscripcion_cbr: sí/no"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "ESCRITURA PÚBLICA DE AUTORIZACIÓN DEL CÓNYUGE. Notaría 3 Santiago, 12-03-2026.\n"
                "Doña MARÍA PÉREZ VEGA, RUT 12.222.222-2, autoriza expresamente la venta del "
                "inmueble declarado bien familiar. Consta subinscripción al margen del CBR."
            ),
            "extractions": [
                {"extraction_class": "tipo_documento", "extraction_text": "autorizacion_conyuge", "attributes": {}},
                {"extraction_class": "notaria_o_tribunal", "extraction_text": "Notaría 3 Santiago", "attributes": {}},
                {"extraction_class": "fecha_documento", "extraction_text": "12-03-2026", "attributes": {}},
                {"extraction_class": "conyuge_nombre", "extraction_text": "MARÍA PÉREZ VEGA", "attributes": {}},
                {"extraction_class": "conyuge_rut", "extraction_text": "12.222.222-2", "attributes": {}},
                {"extraction_class": "consta_subinscripcion_cbr", "extraction_text": "sí", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tipo_documento": None, "notaria_o_tribunal": None, "fecha_documento": None,
            "conyuge_nombre": None, "conyuge_rut": None, "consta_subinscripcion_cbr": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "consta_subinscripcion_cbr":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out


class EscrituraRenunciaUsufructoExtractor(BaseExtractor):
    tipo = "escritura_renuncia_usufructo"

    def prompt(self) -> str:
        return (
            "Extrae de la escritura/comprobante sobre alzamiento de usufructo:\n"
            "  - tipo_comprobante: 'renuncia' (escritura pública) o 'defuncion' (cert. defunción)\n"
            "  - fecha_documento\n"
            "  - usufructuario_nombre + usufructuario_rut\n"
            "  - usufructo_cancelado_cbr: sí/no (si ya está cancelado en el CBR)"
        )

    def examples(self) -> list[dict]:
        return [{
            "text": (
                "ESCRITURA PÚBLICA DE RENUNCIA DE USUFRUCTO. Notaría 3 Santiago, 18-04-2026.\n"
                "Don JUAN ROJAS LIRA, RUT 5.555.555-5, renuncia y alza el usufructo vitalicio "
                "que tenía sobre el inmueble. La cancelación se inscribirá al margen en el CBR."
            ),
            "extractions": [
                {"extraction_class": "tipo_comprobante", "extraction_text": "renuncia", "attributes": {}},
                {"extraction_class": "fecha_documento", "extraction_text": "18-04-2026", "attributes": {}},
                {"extraction_class": "usufructuario_nombre", "extraction_text": "JUAN ROJAS LIRA", "attributes": {}},
                {"extraction_class": "usufructuario_rut", "extraction_text": "5.555.555-5", "attributes": {}},
                {"extraction_class": "usufructo_cancelado_cbr", "extraction_text": "no", "attributes": {}},
            ],
        }]

    def parse(self, lx_extractions) -> dict:
        out = {
            "tipo_comprobante": None, "fecha_documento": None,
            "usufructuario_nombre": None, "usufructuario_rut": None,
            "usufructo_cancelado_cbr": None,
        }
        for ex in lx_extractions:
            cls = _cls(ex); txt = _txt(ex)
            if not cls or txt is None or cls not in out:
                continue
            txt = str(txt).strip()
            if cls == "usufructo_cancelado_cbr":
                out[cls] = txt.lower() in ("sí", "si", "true", "1")
            else:
                out[cls] = txt
        return out


# ─────────────────────────── helpers ───────────────────────────────────────


def _cls(ex):
    return getattr(ex, "extraction_class", None) or (ex.get("extraction_class") if isinstance(ex, dict) else None)


def _txt(ex):
    return getattr(ex, "extraction_text", None) or (ex.get("extraction_text") if isinstance(ex, dict) else None)


def _attrs(ex):
    return getattr(ex, "attributes", {}) or (ex.get("attributes", {}) if isinstance(ex, dict) else {})


def _simple_parse(lx_extractions, fields: list[str]) -> dict:
    """Parser básico: copia campos string tal cual."""
    out: dict = {f: None for f in fields}
    for ex in lx_extractions:
        cls = _cls(ex); txt = _txt(ex)
        if cls in out and txt is not None:
            out[cls] = str(txt).strip()
    return out
