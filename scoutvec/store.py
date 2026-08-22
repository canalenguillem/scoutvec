# scoutvec/store.py
"""Persistencia: MariaDB para metadatos y filtros, Qdrant para los vectores.

El reparto no es decorativo. Qdrant hace lo que numpy no escala a hacer
—vecinos aproximados con filtro por payload— y MariaDB responde lo que un
indice vectorial hace mal: listar, buscar por subcadena, ordenar por minutos
y guardar los 17 percentiles como columnas consultables.

A 1.419 jugadores numpy seguiria siendo mas rapido que ambos. Esto existe
como la forma que tendria el sistema con dos ordenes de magnitud mas de
datos, y el README lo dice sin adornos.
"""
import os
import time

import polars as pl

from scoutvec.vectors import FEATURES

COLECCION = "players"
DIMS = len(FEATURES)

# columna SQL por metrica: los puntos y los % no valen como identificadores
COLS = {f: f.replace(".", "_") for f in FEATURES}


def cfg():
    return dict(
        host=os.getenv("MARIADB_HOST", "mariadb"),
        port=int(os.getenv("MARIADB_PORT", "3306")),
        user=os.getenv("MARIADB_USER", "scoutvec"),
        password=os.getenv("MARIADB_PASSWORD", "scoutvec"),
        database=os.getenv("MARIADB_DATABASE", "scoutvec"),
    )


def conectar(reintentos=30, espera=2):
    """MariaDB tarda en aceptar conexiones aunque el contenedor ya este arriba.

    PyMySQL y no el conector oficial: es Python puro y habla el mismo
    protocolo, lo que ahorra libmariadb-dev y gcc en la imagen.
    """
    import pymysql
    ultimo = None
    for i in range(reintentos):
        try:
            return pymysql.connect(**cfg(), autocommit=False,
                                   charset="utf8mb4")
        except pymysql.Error as e:      # noqa: PERF203
            ultimo = e
            print(f"  mariadb no lista ({i + 1}/{reintentos}): {e}", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"no hay MariaDB tras {reintentos} intentos: {ultimo}")


def qdrant(reintentos=30, espera=2):
    from qdrant_client import QdrantClient
    url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    ultimo = None
    for i in range(reintentos):
        try:
            c = QdrantClient(url=url, timeout=10)
            c.get_collections()
            return c
        except Exception as e:          # noqa: BLE001, PERF203
            ultimo = e
            print(f"  qdrant no listo ({i + 1}/{reintentos}): {e}", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"no hay Qdrant tras {reintentos} intentos: {ultimo}")


DDL = f"""
CREATE TABLE IF NOT EXISTS players (
  id            INT PRIMARY KEY,
  name          VARCHAR(120) NOT NULL,
  team          VARCHAR(80)  NOT NULL,
  league        VARCHAR(40)  NOT NULL,
  role          CHAR(2)      NOT NULL,
  minutes       INT          NOT NULL,
  possession    DECIMAL(6,4) NOT NULL,
  {chr(10).join(f'  {c:<22} DECIMAL(6,4) NOT NULL,' for c in COLS.values())}
  INDEX idx_league (league),
  INDEX idx_role   (role),
  INDEX idx_team   (team),
  INDEX idx_name   (name),
  INDEX idx_min    (minutes)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def sembrar(parquet="vectors.parquet"):
    """Carga vectors.parquet en ambos almacenes. Idempotente: reescribe todo."""
    from qdrant_client import models

    d = pl.read_parquet(parquet)
    print(f"sembrando {len(d)} jugadores desde {parquet}", flush=True)

    # --- MariaDB -----------------------------------------------------------
    con = conectar()
    cur = con.cursor()
    cur.execute(DDL)
    cur.execute("DELETE FROM players")

    campos = ["id", "name", "team", "league", "role", "minutes",
              "possession"] + list(COLS.values())
    sql = (f"INSERT INTO players ({','.join(campos)}) "
           f"VALUES ({','.join(['%s'] * len(campos))})")
    filas = [
        (int(r["player_id"]), r["player"], r["team"], r["league"], r["role"],
         int(r["minutos"]), float(r["posesion"]),
         *[float(r[f"pct_{f}"]) for f in FEATURES])
        for r in d.iter_rows(named=True)
    ]
    cur.executemany(sql, filas)
    con.commit()
    cur.execute("SELECT COUNT(*) FROM players")
    n_sql = cur.fetchone()[0]
    con.close()
    print(f"  mariadb: {n_sql} filas", flush=True)

    # --- Qdrant ------------------------------------------------------------
    qc = qdrant()
    if qc.collection_exists(COLECCION):
        qc.delete_collection(COLECCION)
    qc.create_collection(
        collection_name=COLECCION,
        vectors_config=models.VectorParams(size=DIMS,
                                           distance=models.Distance.COSINE),
    )
    # el payload existe para filtrar dentro del indice, no para leerlo
    for campo in ("role", "league", "team"):
        qc.create_payload_index(COLECCION, campo,
                                field_schema=models.PayloadSchemaType.KEYWORD)

    qc.upsert(COLECCION, points=[
        models.PointStruct(
            id=int(r["player_id"]),
            vector=[float(r[f"pct_{f}"]) for f in FEATURES],
            payload={"role": r["role"], "league": r["league"], "team": r["team"]},
        )
        for r in d.iter_rows(named=True)
    ], wait=True)
    n_q = qc.count(COLECCION, exact=True).count
    print(f"  qdrant : {n_q} puntos", flush=True)

    if n_sql != len(d) or n_q != len(d):
        raise SystemExit(f"siembra incompleta: parquet={len(d)} "
                         f"mariadb={n_sql} qdrant={n_q}")
    print("siembra ok", flush=True)


if __name__ == "__main__":
    sembrar(os.getenv("VECTORS_PATH", "vectors.parquet"))
