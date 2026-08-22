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

from scoutvec.datasets import DATASETS, disponibles, get
from scoutvec.vectors import FEATURES

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
  dataset       VARCHAR(32) NOT NULL,
  id            INT NOT NULL,
  name          VARCHAR(120) NOT NULL,
  team          VARCHAR(80)  NOT NULL,
  league        VARCHAR(40)  NOT NULL,
  role          CHAR(2)      NOT NULL,
  minutes       INT          NOT NULL,
  possession    DECIMAL(6,4) NOT NULL,
  {chr(10).join(f'  {c:<22} DECIMAL(6,4) NOT NULL,' for c in COLS.values())}
  PRIMARY KEY (dataset, id),
  INDEX idx_dataset (dataset),
  INDEX idx_league (league),
  INDEX idx_role   (role),
  INDEX idx_team   (team),
  INDEX idx_name   (name),
  INDEX idx_min    (minutes)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def crear_usuario_inicial(cur, usuario, password):
    """Crea el usuario si no existe. Idempotente: no pisa uno ya creado."""
    from scoutvec import auth
    cur.execute("SELECT id FROM users WHERE username = %s", (usuario,))
    if cur.fetchone():
        print(f"  usuario {usuario!r} ya existe, no se toca", flush=True)
        return False
    cur.execute(
        "INSERT INTO users (username, password_hash, must_change) "
        "VALUES (%s, %s, 1)", (usuario, auth.hashear(password)))
    print(f"  usuario {usuario!r} creado, debe cambiar la clave al entrar",
          flush=True)
    return True


def sembrar():
    """Carga cada dataset generado en ambos almacenes. Idempotente."""
    from qdrant_client import models
    from scoutvec import auth

    listos = disponibles()
    if not listos:
        raise SystemExit("ningun dataset generado; ejecuta el pipeline")
    print(f"datasets a sembrar: {[x.slug for x in listos]}", flush=True)

    # --- MariaDB -----------------------------------------------------------
    con = conectar()
    cur = con.cursor()

    # players es derivada: si le falta una columna se recrea sin mas. users y
    # sessions NUNCA se tocan aqui — ahi viven las contraseñas.
    cur.execute("SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'players' "
                "AND column_name = 'dataset'")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = 'players'")
        if cur.fetchone()[0]:
            print("  esquema antiguo de players: se recrea", flush=True)
            cur.execute("DROP TABLE players")
    cur.execute(DDL)
    for sentencia in auth.DDL.strip().split(";"):
        if sentencia.strip():
            cur.execute(sentencia)

    usuario = os.getenv("ADMIN_USER", "").strip()
    clave = os.getenv("ADMIN_INITIAL_PASSWORD", "").strip()
    if usuario and clave:
        crear_usuario_inicial(cur, usuario, clave)
    elif usuario:
        print(f"  aviso: ADMIN_USER={usuario!r} sin ADMIN_INITIAL_PASSWORD",
              flush=True)

    qc = qdrant()
    campos = ["dataset", "id", "name", "team", "league", "role", "minutes",
              "possession"] + list(COLS.values())
    sql = (f"INSERT INTO players ({','.join(campos)}) "
           f"VALUES ({','.join(['%s'] * len(campos))})")

    for ds in listos:
        d = pl.read_parquet(ds.vectores)
        cur.execute("DELETE FROM players WHERE dataset = %s", (ds.slug,))
        cur.executemany(sql, [
            (ds.slug, int(r["player_id"]), r["player"], r["team"], r["league"],
             r["role"], int(r["minutos"]), float(r["posesion"]),
             *[float(r[f"pct_{f}"]) for f in FEATURES])
            for r in d.iter_rows(named=True)])
        con.commit()
        cur.execute("SELECT COUNT(*) FROM players WHERE dataset = %s",
                    (ds.slug,))
        n_sql = cur.fetchone()[0]

        # una coleccion por dataset: sus percentiles salen de poblaciones
        # distintas, mezclarlos en un mismo indice seria un error silencioso
        if qc.collection_exists(ds.coleccion):
            qc.delete_collection(ds.coleccion)
        qc.create_collection(
            collection_name=ds.coleccion,
            vectors_config=models.VectorParams(
                size=DIMS, distance=models.Distance.COSINE))
        # el payload existe para filtrar dentro del indice, no para leerlo
        for campo in ("role", "league", "team"):
            qc.create_payload_index(
                ds.coleccion, campo,
                field_schema=models.PayloadSchemaType.KEYWORD)
        qc.upsert(ds.coleccion, points=[
            models.PointStruct(
                id=int(r["player_id"]),
                vector=[float(r[f"pct_{f}"]) for f in FEATURES],
                payload={"role": r["role"], "league": r["league"],
                         "team": r["team"]})
            for r in d.iter_rows(named=True)], wait=True)
        n_q = qc.count(ds.coleccion, exact=True).count

        print(f"  {ds.slug:16s} parquet={len(d)} mariadb={n_sql} "
              f"qdrant={n_q}", flush=True)
        if n_sql != len(d) or n_q != len(d):
            raise SystemExit(f"siembra incompleta de {ds.slug}")

    con.close()
    print("siembra ok", flush=True)


if __name__ == "__main__":
    sembrar()
