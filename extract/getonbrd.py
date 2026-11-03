"""
Extrae vacantes de datos desde la API pública de Get on Board y las guarda en
PostgreSQL (Neon), en la tabla raw.getonbrd_vacantes.

Qué hace, paso a paso:
  1. Crea las tablas si no existen (sql/001_crear_tablas.sql).
  2. Busca cada término de TERMINOS en la API, página por página.
  3. Junta los resultados: si una vacante sale en varias búsquedas, queda una sola.
  4. Hace un "upsert": inserta las vacantes nuevas y, a las que ya existían,
     solo les actualiza la fecha de última vista (así no se repiten registros).
  5. Registra la ejecución en raw.ejecuciones.

No filtra por país: guarda todo lo que encuentra. El filtro "solo Colombia"
se hace después en dbt, para no perder datos si cambias de opinión.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import requests
from psycopg.types.json import Jsonb

API = "https://www.getonbrd.com/api/v0"
FUENTE = "getonbrd"

# Términos de búsqueda: mezcla de roles y habilidades (español e inglés,
# porque muchas vacantes en español usan títulos en inglés).
TERMINOS = [
    "datos",
    "analista de datos",
    "data analyst",
    "analytics engineer",
    "data engineer",
    "business intelligence",
    "power bi",
    "dbt",
    "calidad de datos",
    "data quality",
    "etl",
    "sql",
]

POR_PAGINA = 100          # máximo que permite la API
MAX_PAGINAS = 20          # freno de seguridad por término
PAUSA_SEG = 1.0           # pausa entre peticiones, para no saturar el servidor

# Campos que cambian casi a diario y no significan un cambio real de la vacante.
# Se excluyen del hash para que last_changed_at solo se mueva con cambios de verdad.
CAMPOS_VOLATILES = {"applications_count"}

RAIZ = Path(__file__).resolve().parent.parent
SQL_TABLAS = RAIZ / "sql" / "001_crear_tablas.sql"


def buscar(termino: str) -> list[dict]:
    """Devuelve todas las vacantes de un término, recorriendo las páginas."""
    vacantes = []
    for pagina in range(1, MAX_PAGINAS + 1):
        r = requests.get(
            f"{API}/search/jobs",
            params={"query": termino, "per_page": POR_PAGINA, "page": pagina},
            headers={"Accept": "application/json",
                     "User-Agent": "proyecto-portafolio-vacantes-datos"},
            timeout=30,
        )
        r.raise_for_status()                      # si la API falla, se detiene con error
        datos = r.json().get("data", [])
        vacantes.extend(datos)
        if len(datos) < POR_PAGINA:               # página incompleta = era la última
            break
        time.sleep(PAUSA_SEG)
    return vacantes


def huella(vacante: dict) -> str:
    """Hash SHA-256 del contenido, sin los campos volátiles."""
    atributos = {k: v for k, v in vacante.get("attributes", {}).items()
                 if k not in CAMPOS_VOLATILES}
    texto = json.dumps(atributos, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def main() -> None:
    url_bd = os.environ.get("DATABASE_URL")
    if not url_bd:
        sys.exit("Falta la variable DATABASE_URL (la cadena de conexión de Neon).")

    inicio = datetime.now(timezone.utc)

    with psycopg.connect(url_bd) as conn:
        conn.execute(SQL_TABLAS.read_text(encoding="utf-8"))
        run_id = conn.execute(
            "INSERT INTO raw.ejecuciones (fuente, inicio, estado) "
            "VALUES (%s, %s, 'en curso') RETURNING run_id",
            (FUENTE, inicio),
        ).fetchone()[0]
        conn.commit()

        try:
            # 1) Extraer y quitar duplicados dentro de la misma ejecución
            unicas: dict[str, dict] = {}
            for termino in TERMINOS:
                for v in buscar(termino):
                    item = unicas.setdefault(v["id"], {"vacante": v, "consultas": set()})
                    item["consultas"].add(termino)
                print(f"'{termino}': acumuladas {len(unicas)} vacantes únicas")
                time.sleep(PAUSA_SEG)

            # 2) Upsert: nueva -> se inserta; existente -> se actualiza la fecha
            filas = [
                (job_id, Jsonb(i["vacante"]), huella(i["vacante"]),
                 sorted(i["consultas"]), inicio)
                for job_id, i in unicas.items()
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO raw.getonbrd_vacantes AS t
                        (job_id, payload, payload_hash, consultas,
                         first_seen_at, last_seen_at, last_changed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE SET
                        last_seen_at    = EXCLUDED.last_seen_at,
                        payload         = EXCLUDED.payload,
                        consultas       = ARRAY(SELECT DISTINCT unnest(t.consultas || EXCLUDED.consultas)),
                        last_changed_at = CASE WHEN t.payload_hash <> EXCLUDED.payload_hash
                                               THEN EXCLUDED.last_changed_at
                                               ELSE t.last_changed_at END,
                        payload_hash    = EXCLUDED.payload_hash
                    """,
                    [(f[0], f[1], f[2], f[3], f[4], f[4], f[4]) for f in filas],
                )

            # 3) Contar cuántas eran nuevas (las que se vieron por primera vez hoy)
            nuevas = conn.execute(
                "SELECT count(*) FROM raw.getonbrd_vacantes WHERE first_seen_at = %s",
                (inicio,),
            ).fetchone()[0]

            conn.execute(
                "UPDATE raw.ejecuciones SET fin = now(), vacantes_leidas = %s, "
                "vacantes_nuevas = %s, estado = 'ok' WHERE run_id = %s",
                (len(unicas), nuevas, run_id),
            )
            conn.commit()
            print(f"OK: {len(unicas)} vacantes únicas leídas, {nuevas} nuevas.")

        except Exception as e:
            conn.rollback()
            conn.execute(
                "UPDATE raw.ejecuciones SET fin = now(), estado = 'error', mensaje = %s "
                "WHERE run_id = %s",
                (str(e)[:1000], run_id),
            )
            conn.commit()
            raise


if __name__ == "__main__":
    main()
