"""
Catálogo de tipos de documento — espejo del que vive en clasificador-api.
Mantener sincronizado: si agregas un código aquí, agrégalo también en
clasificador-api/src/models/catalogo.py y en migrations/dt_clasificaciones.

Esta lista es la fuente de verdad para validar `tipo` en el extract endpoint.
"""
CODIGOS_VALIDOS: list[str] = [
    # identidad
    "carnet_identidad",
    # estado_civil
    "cert_matrimonio", "cert_union_civil", "cert_solteria", "decl_jurada_solteria", "cert_defuncion",
    # cbr
    "cert_dominio_vigente", "cert_hipotecas_gravamenes",
    # escrituras
    "escritura", "escritura_compraventa", "escritura_anterior",
    "escritura_alzamiento_hipoteca", "escritura_bien_familiar", "escritura_renuncia_usufructo",
    # tributario
    "cert_deuda_contribuciones", "cert_avaluo_sii",
    # urbanismo
    "cert_no_expropiacion_dom", "cert_no_expropiacion_serviu",
    "cert_numero_dom", "cert_recepcion_final_dom",
    "cert_municipal",  # legacy genérico
    "plano_propiedad", "plan_regulador",
    # persona juridica
    "e_rut_sii", "escritura_constitucion_social", "cert_vigencia_poderes",
    # condominio
    "cert_deuda_gastos_comunes", "acta_asamblea_copropietarios",
    # serviu
    "resolucion_serviu",
    # tribunales
    "sentencia_judicial", "cert_ejecutoria",
    # rural
    "cert_subdivision_sag", "plano_subdivision_sag",
    # indigena
    "cert_conadi",
    # herencia
    "cert_posesion_efectiva", "cert_exencion_herencia_sii",
    # fallback
    "otro",
]
