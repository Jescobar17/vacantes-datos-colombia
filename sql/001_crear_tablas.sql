-- =====================================================================
-- Capa RAW: los datos se guardan tal como llegan de la fuente.
-- La limpieza y el modelado se hacen después en dbt (trabajo de AE).
-- Este archivo es idempotente: se puede correr muchas veces sin romper nada.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;

-- Una fila por vacante (job_id). Si la vacante vuelve a aparecer otro día,
-- NO se crea una fila nueva: solo se actualiza last_seen_at.
CREATE TABLE IF NOT EXISTS raw.getonbrd_vacantes (
    job_id           TEXT PRIMARY KEY,          -- id único de la vacante en Get on Board
    payload          JSONB       NOT NULL,      -- respuesta completa de la API (sin tocar)
    payload_hash     TEXT        NOT NULL,      -- huella del contenido, para detectar cambios
    consultas        TEXT[]      NOT NULL,      -- términos de búsqueda que la encontraron
    first_seen_at    TIMESTAMPTZ NOT NULL,      -- primer día que la vimos
    last_seen_at     TIMESTAMPTZ NOT NULL,      -- último día que la vimos (si deja de verse, se cerró)
    last_changed_at  TIMESTAMPTZ NOT NULL       -- último día que cambió su contenido
);

-- Bitácora de ejecuciones: sirve para tests de frescura y volumen.
CREATE TABLE IF NOT EXISTS raw.ejecuciones (
    run_id           BIGSERIAL PRIMARY KEY,
    fuente           TEXT        NOT NULL,
    inicio           TIMESTAMPTZ NOT NULL,
    fin              TIMESTAMPTZ,
    vacantes_leidas  INTEGER,                   -- vacantes únicas recibidas en esta ejecución
    vacantes_nuevas  INTEGER,                   -- vacantes que nunca habíamos visto
    estado           TEXT        NOT NULL,      -- 'ok' o 'error'
    mensaje          TEXT
);
