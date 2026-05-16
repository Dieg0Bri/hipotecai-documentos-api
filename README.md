# documentos-api

Servicio Python/FastAPI que extrae **datos estructurados específicos por tipo de documento** legal hipotecario chileno usando langextract sobre Gemini. Cada tipo (escritura, certificado CBR, certificado SII, certificado municipal, plano, plan regulador) tiene su propio extractor con prompt + ejemplos few-shot calibrados.

## Endpoints

| Método | Ruta                                       | Descripción |
|--------|--------------------------------------------|-------------|
| GET    | `/health`                                  | Health |
| POST   | `/extract`                                 | Extracción dado el texto plano + tipo |
| POST   | `/extract-from-gcs`                        | Descarga del bucket → extrae texto → extrae campos → persiste en `dt_extraccion` |
| GET    | `/archivos/{id_archivo}/ocr`               | Metadata del .md OCR (gcs_uri, offsets por página, bbox/conf por línea) |
| GET/POST/PATCH/DELETE | `/anchors/...`                | CRUD de anchors (evidencia navegable, migración 010) |

La **firma del `.md` OCR** para descargarlo en el visor NO vive acá — la
hace `ingestion-service` junto con la del PDF original, en
`/api-ingestion/upload/ocr-download-url`. Razón: tenant scoping y manejo
de archivos están centralizados ahí; documentos-api solo expone la
metadata del OCR (offsets, bbox, confidence) y la lógica de extracción.

## Extractors disponibles

| Tipo | Extractor | Schema Pydantic |
|------|-----------|-----------------|
| `escritura`                   | `EscrituraExtractor`         | tipo_acto, vendedor/comprador, precio CLP/UF, foja, repertorio, rol, superficie |
| `cert_dominio_vigente`        | `CertDominioVigenteExtractor`| CBR emisor, foja, número/año inscripción, titular, RUT, dirección |
| `cert_hipotecas_gravamenes`   | `CertHipotecasExtractor`     | hipotecas, prohibiciones, gravámenes, interdicciones, libre_de_gravamenes |
| `cert_avaluo_sii`             | `CertAvaluoSiiExtractor`     | rol_avaluo, avalúos terreno/construcción/total, superficies, destino, exenciones |
| `cert_municipal`              | `CertMunicipalExtractor`     | número municipal, no_expropiacion, recepción final, permiso edificación |
| `plano_propiedad`             | `PlanoPropiedadExtractor`    | tipo_plano, superficies, deslindes, profesional, fecha |
| `plan_regulador`              | `PlanReguladorExtractor`     | comuna, zonificación, usos, altura, coef. constructibilidad/ocupación |

Cada extractor devuelve `ExtractionResult` con:
- `datos`: campos tipados según el schema
- `confianza`: proporción de campos no nulos (0-1)
- `spans`: list[{field, value, start_char, end_char}] para resaltar en el visor PDF

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # configurar GEMINI_API_KEY
uvicorn main:app --reload --host 0.0.0.0 --port 8085
```

## Cómo agregar un nuevo extractor

1. Crear `src/extractors/<tipo>.py` heredando `BaseExtractor`
2. Implementar `prompt()`, `examples()` (lista de 1-3 documentos representativos), `parse()` (mapeo lx_extractions → dict)
3. Registrar en `get_extractor()` (`src/extractors/base.py`)
4. Agregar el `Literal[...]` en `src/models/schemas.py` (TipoDocumento)
