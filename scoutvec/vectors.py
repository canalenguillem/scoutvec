import os
from pathlib import Path

import numpy as np
import polars as pl

from scoutvec.features import RATIOS
from scoutvec.roles import POS2ROLE

SALIDA = Path("vectors.parquet")

# 11 volumenes p90 + 6 ratios. Los ratios son los que no escalan con la
# posesion del equipo, que es la fuga de contexto documentada en PROJECT.md.
VOLUMENES = ["pass_p90", "shot_p90", "dribble_p90", "pressure_p90",
             "carry_p90", "ball_receipt_p90", "duel_p90",
             "interception_p90", "clearance_p90",
             "prog_pass_p90", "prog_carry_p90"]

FEATURES = VOLUMENES + RATIOS


def residualiza(d, cols):
    """Quita de cada metrica su componente lineal en la posesion del equipo.

    Se residualiza, no se divide: la relacion metrica-posesion es afin
    (a + b*pos), asi que dividir da a/pos + b, que decrece con la posesion
    e introduce el agrupamiento que se pretendia quitar. Medido: dividir
    deja la correlacion en 0.572, residualizar en 0.448, sin tocar 0.695.
    """
    pos = d["posesion"].to_numpy()
    ajustadas = []
    for f in cols:
        y = d[f].to_numpy().astype(float)
        b = np.polyfit(pos, y, 1)
        ajustadas.append(pl.Series(f"adj_{f}", y - np.polyval(b, pos)))
    return d.with_columns(ajustadas)


def run(over=None, escribe=True, normalizar=True):
    """over: solo para probar el canario. En produccion el percentil es GLOBAL."""
    if escribe and SALIDA.exists():
        os.remove(SALIDA)

    d = pl.read_parquet("players.parquet")
    d = d.with_columns(
        pl.col("position").replace_strict(POS2ROLE, default=None).alias("role")
    )

    sin_rol = d.filter(pl.col("role").is_null())
    if len(sin_rol):
        print("SIN ROL:", sin_rol["position"].unique().to_list())

    d = d.filter(pl.col("role").is_not_null() & (pl.col("role") != "GK"))

    # rellenar aqui, no en features: la mediana debe salir de la poblacion
    # que se rankea (jugadores de campo), sin porteros dentro
    huecos = {c: d[c].null_count() for c in RATIOS if d[c].null_count()}
    if huecos:
        print("ratios rellenados con la mediana de campo:", huecos)
    d = d.with_columns([pl.col(c).fill_null(pl.col(c).median()) for c in RATIOS])

    # la residualizacion va antes del percentil y despues de excluir porteros:
    # el ajuste debe calcularse sobre la poblacion que se rankea
    if normalizar:
        d = residualiza(d, FEATURES)
        base = {f: f"adj_{f}" for f in FEATURES}
    else:
        base = {f: f for f in FEATURES}

    if over is None:
        rank = [(pl.col(base[f]).rank("average") / pl.len()).round(4)
                .alias(f"pct_{f}") for f in FEATURES]
    else:
        rank = [(pl.col(base[f]).rank("average").over(over) /
                 pl.len().over(over)).round(4).alias(f"pct_{f}")
                for f in FEATURES]
    d = d.with_columns(rank)

    pct = [f"pct_{f}" for f in FEATURES]

    # Con percentil GLOBAL y rank("average"), solo un jugador puede alcanzar
    # 1.0 en cada metrica: un empate en el maximo reparte el rango medio y
    # baja de 1.0. Si dos o mas lo alcanzan, el ranking se ha calculado por
    # grupos (rol o liga) y el vector pierde la informacion posicional.
    topes = {c: d.filter(pl.col(c) == 1.0) for c in pct}
    malas = {c: t for c, t in topes.items() if t.height > 1}
    if malas:
        for c, t in malas.items():
            print(f"  {c}: {t.height} jugadores con percentil 1.0 ->",
                  t["player"].to_list()[:8])
        raise AssertionError(
            f"percentil 1.0 duplicado en {sorted(malas)} — "
            f"el ranking no es global")

    print("tope de cada metrica (uno por metrica, percentil global):")
    for c in pct:
        t = topes[c]
        if t.height == 1:
            print(f"  {c:24s} {t['player'][0]}  ({t['league'][0]}, {t['role'][0]})")

    d = d.with_columns(pl.concat_list(pct).alias("vector"))

    if escribe:
        d.write_parquet(SALIDA)

    print(d.group_by("role").agg(pl.len().alias("n")).sort("role"))
    print(d.group_by("league").agg(pl.len().alias("n")).sort("league"))
    print(d.filter(pl.col("player").str.contains("Messi"))
           .select(["player", "league", "role", "pct_dribble_p90", "pct_pass_p90"])
           .to_pandas().to_string())


if __name__ == "__main__":
    run()