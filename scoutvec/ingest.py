# scoutvec/ingest.py
import argparse
import os
from pathlib import Path

import polars as pl
from tqdm import tqdm

from scoutvec.datasets import DATASETS, POR_DEFECTO, get
from scoutvec.fetch import matches, events

DEST = Path("data")

SCHEMA = {
    "league": pl.String,
    "match_id": pl.Int64,
    "player_id": pl.Int64,
    "player": pl.String,
    "team": pl.String,
    "position": pl.String,
    "type": pl.String,
    "minute": pl.Int32,
    "period": pl.Int32,
    "x": pl.Float64,
    "y": pl.Float64,
    "end_x": pl.Float64,
    "end_y": pl.Float64,
    "pass_len": pl.Float64,
    "pass_type": pl.String,
    "duel_type": pl.String,
    "presion": pl.Boolean,
    "aereo_ganado": pl.Boolean,
    "xg": pl.Float64,
    "outcome": pl.String,
}

# el campo de StatsBomb son 120x80 YARDAS y el equipo siempre ataca hacia
# x=120, asi que las coordenadas ya vienen normalizadas por sentido de juego.
PORTERIA = (120.0, 40.0)

# cuantos partidos se acumulan como dicts antes de volcarlos a DataFrame.
# Un DataFrame de polars ocupa ~4x menos que la misma fila como dict, asi
# que trocear acota el pico de memoria sin importar cuantas columnas haya.
CHUNK = 50


def slug(n):
    return n.lower().replace(" ", "_")


def flatten(e, match_id, league):
    """Un evento anidado de StatsBomb → una fila plana. None si no hay jugador."""
    p = e.get("player")
    if p is None:  # Half Start, Starting XI, Tactical Shift...
        return None
    loc = e.get("location") or [None, None]
    ps = e.get("pass") or {}
    ca = e.get("carry") or {}
    du = e.get("duel") or {}

    # el destino vive en pass.end_location o carry.end_location
    fin = ps.get("end_location") or ca.get("end_location") or [None, None]

    # un aereo ganado no es un Duel: StatsBomb lo marca con aerial_won
    # dentro del evento que lo resuelve (pase, despeje, tiro, miscontrol).
    # El perdido si es Duel con duel.type == "Aerial Lost".
    aereo = any((e.get(k) or {}).get("aerial_won")
                for k in ("pass", "clearance", "shot", "miscontrol"))

    return {
        "league": league,
        "match_id": match_id,
        "player_id": p["id"],
        "player": p["name"],
        "team": e["team"]["name"],
        "position": (e.get("position") or {}).get("name"),
        "type": e["type"]["name"],
        "minute": e["minute"],
        "period": e["period"],
        "x": loc[0],
        "y": loc[1],
        "end_x": fin[0],
        "end_y": fin[1],
        "pass_len": ps.get("length"),
        "pass_type": (ps.get("type") or {}).get("name"),
        "duel_type": (du.get("type") or {}).get("name"),
        "presion": bool(e.get("under_pressure")),
        "aereo_ganado": aereo,
        "xg": (e.get("shot") or {}).get("statsbomb_xg"),
        "outcome": ((ps or e.get("dribble") or {})
                    .get("outcome") or {}).get("name"),
    }


def una_liga(ds, league, comp, season):
    """Ingesta una liga a su propio parquet. Devuelve (ruta, filas)."""
    destino = ds.eventos_liga(league)
    if destino.exists():
        os.remove(destino)

    trozos, rows = [], []
    ms = matches(comp, season)
    for k, m in enumerate(tqdm(ms, desc=league), 1):
        for e in events(m["match_id"]):
            r = flatten(e, m["match_id"], league)
            if r:
                rows.append(r)
        if k % CHUNK == 0:
            trozos.append(pl.DataFrame(rows, schema=SCHEMA))
            rows = []
    if rows:
        trozos.append(pl.DataFrame(rows, schema=SCHEMA))
    del rows

    df = pl.concat(trozos)
    del trozos
    df.write_parquet(destino)
    n = len(df)
    del df  # el pico de memoria es una liga, no las cuatro
    print(f"  {league}: {n:,} eventos -> {destino}")
    return destino, n


def run(dataset=None, ligas=None):
    ds = get(dataset)
    ligas = ligas or list(ds.ligas)

    # validar ANTES de borrar: un nombre mal escrito no debe destruir la salida
    malas = [n for n in ligas if n not in ds.ligas]
    if malas:
        raise ValueError(f"liga desconocida en {ds.slug}: {malas} — "
                         f"validas: {list(ds.ligas)}")

    DEST.mkdir(exist_ok=True)
    print(f"dataset {ds.slug} ({ds.temporada}): {', '.join(ligas)}", flush=True)

    # borrar antes de regenerar: un fallo no debe dejar datos viejos en su sitio
    if ds.eventos.exists():
        os.remove(ds.eventos)

    partes, total = [], 0
    for n in ligas:
        ruta, filas = una_liga(ds, n, *ds.ligas[n])
        partes.append(ruta)
        total += filas

    # concatenado en streaming, sin materializar las cuatro ligas a la vez
    pl.concat([pl.scan_parquet(p) for p in partes]).sink_parquet(ds.eventos)

    df = pl.scan_parquet(ds.eventos)
    resumen = (df.group_by("league")
                 .agg([pl.len().alias("eventos"),
                       pl.col("match_id").n_unique().alias("partidos"),
                       pl.col("player_id").n_unique().alias("jugadores")])
                 .sort("league").collect())
    print(resumen)
    print(f"total: {total:,} eventos -> {ds.eventos} "
          f"({ds.eventos.stat().st_size / 2**20:.1f} MiB)")
    assert resumen["eventos"].sum() == total, "el concatenado perdio filas"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m scoutvec.ingest")
    ap.add_argument("-d", "--dataset", default=POR_DEFECTO,
                    choices=list(DATASETS), help="que conjunto de ligas")
    ap.add_argument("ligas", nargs="*", default=None,
                    help="por defecto, todas las del dataset")
    a = ap.parse_args()
    run(a.dataset, a.ligas or None)