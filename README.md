# Mercado laboral de datos en Colombia

Proyecto de portafolio: qué piden las empresas en Colombia para roles de datos
(analista, BI, calidad de datos, Analytics Engineering), qué herramientas,
qué salarios y qué sectores.

## Arquitectura

```
API pública Get on Board ──(Python, diario vía GitHub Actions)──> Neon PostgreSQL (raw)
                                                                      │
                                                    dbt: staging → intermediate → marts
                                                                      │
                                                                  Power BI
```

## Capa raw (ingesta)

- `raw.getonbrd_vacantes`: una fila por vacante. Si la vacante sigue publicada
  varios días, no se duplica: se actualiza `last_seen_at`.
  `last_seen_at - first_seen_at` ≈ días que estuvo publicada.
- `raw.ejecuciones`: bitácora de cada ejecución (leídas, nuevas, estado).

La extracción no filtra por país; el filtro "Colombia" se aplica en dbt.

## Cómo correrlo

1. Crear la base en Neon y copiar la cadena de conexión.
2. Guardarla en GitHub: Settings → Secrets and variables → Actions → `DATABASE_URL`.
3. Actions → "Extraer vacantes" → Run workflow.

## Fuente

Datos de la [API pública de Get on Board](https://www.getonbrd.com/api-doc.html),
que la plataforma ofrece para análisis del mercado laboral sin necesidad de login.
