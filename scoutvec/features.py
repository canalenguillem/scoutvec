# scoutvec/features.py
import os
from pathlib import Path

import polars as pl

MIN_MINUTOS = 600
SALIDA = Path("players.parquet")

METRICAS = ["Pass", "Shot", "Dribble", "Pressure", "Carry",
            "Ball Receipt*", "Duel", "Interception", "Clearance"]

# eventos que suponen contacto con el balon, para la zona de contacto
TOQUES = ["Pass", "Carry", "Ball Receipt*", "Shot", "Dribble"]

# proxy de posesion: cuota del equipo en acciones con balon dentro del partido
ACCIONES = ["Pass", "Carry", "Ball Receipt*", "Dribble", "Shot"]

# umbrales de progresion, en yardas de acercamiento a la porteria rival.
# El carry usa un umbral menor porque conducir 10 yardas es mucho mas raro
# que pasarlas.
PROG_PASE, PROG_CARRY = 10.0, 5.0
PASE_LARGO = 30.0

# denominadores por debajo de esto dan un ratio ruidoso; se marcan nulos y
# luego se rellenan con la mediana de la columna
MIN_DENOM = 20

RATIOS = ["pass_completion", "pass_comp_pressure", "pass_forward_share",
          "pass_long_share", "touch_final_third", "aerial_win"]


def slug(c):
    return c.lower().replace(" ", "_").replace("*", "")


def _dist(x, y):
    """Distancia a la porteria rival, siempre en (120, 40)."""
    return ((120 - pl.col(x)) ** 2 + (40 - pl.col(y)) ** 2).sqrt()


def derivadas(ev):
    """Ratios y conteos que necesitan las columnas espaciales."""
    avance = _dist("x", "y") - _dist("end_x", "end_y")

    es_pase = pl.col("type") == "Pass"
    abierto = es_pase & pl.col("pass_type").is_null()   # sin corners ni saques
    completo = pl.col("outcome").is_null()
    es_carry = pl.col("type") == "Carry"
    toque = pl.col("type").is_in(TOQUES)

    return ev.group_by("player_id").agg([
        # volumenes nuevos
        (abierto & completo & (avance >= PROG_PASE)).sum().alias("prog_pass"),
        (es_carry & (avance >= PROG_CARRY)).sum().alias("prog_carry"),

        # ratios de pase (juego abierto)
        abierto.sum().alias("_n_pases"),
        (abierto & completo).sum().alias("_ok"),
        (abierto & pl.col("presion")).sum().alias("_n_pres"),
        (abierto & pl.col("presion") & completo).sum().alias("_ok_pres"),
        (abierto & (pl.col("end_x") > pl.col("x") + 2)).sum().alias("_adelante"),
        (abierto & (pl.col("pass_len") >= PASE_LARGO)).sum().alias("_largos"),

        # zona de contacto
        toque.sum().alias("_n_toques"),
        (toque & (pl.col("x") >= 80)).sum().alias("_ult_tercio"),

        # duelos aereos: el ganado se marca con aerial_won en el evento que
        # lo resuelve, el perdido es un Duel de tipo "Aerial Lost"
        pl.col("aereo_ganado").sum().alias("_aer_gan"),
        (pl.col("duel_type") == "Aerial Lost").sum().alias("_aer_perd"),
    ])


def ratio(num, den, nombre):
    """num/den, nulo si el denominador no da para un ratio estable."""
    return (pl.when(pl.col(den) >= MIN_DENOM)
              .then(pl.col(num) / pl.col(den))
              .otherwise(None)
              .round(4).alias(nombre))


def posesion(ev):
    """Cuota de posesion del equipo del jugador, ponderada por minutos.

    Es un proxy por conteo de acciones, no posesion cronometrada, pero se
    valida solo: la media sale en 0.500 exacto porque las cuotas de los dos
    equipos suman 1 en cada partido.
    """
    cuota = (ev.filter(pl.col("type").is_in(ACCIONES))
               .group_by(["match_id", "team"]).agg(pl.len().alias("n"))
               .with_columns((pl.col("n") / pl.col("n").sum().over("match_id"))
                             .alias("cuota"))
               .select(["match_id", "team", "cuota"]))

    pm = (ev.group_by(["player_id", "match_id", "team"])
            .agg((pl.col("minute").max() - pl.col("minute").min()).alias("m")))

    return (pm.join(cuota, on=["match_id", "team"])
              .group_by("player_id")
              .agg(((pl.col("cuota") * pl.col("m")).sum() /
                    pl.col("m").sum()).round(4).alias("posesion")))


def run():
    # borrar antes de nada: si esto falla, no debe quedar un parquet viejo
    # que parezca recien generado
    if SALIDA.exists():
        os.remove(SALIDA)

    ev = pl.read_parquet("data/events.parquet")

    # minutos ≈ (último - primer evento) por jugador y partido
    por_partido = (ev.group_by(["player_id", "player", "league", "team",
                                "match_id"])
                     .agg((pl.col("minute").max() - pl.col("minute").min())
                          .alias("m")))

    minutos = (por_partido.group_by(["player_id", "player"])
                 .agg([pl.col("m").sum().alias("minutos"),
                       pl.len().alias("partidos"),
                       pl.col("league").n_unique().alias("n_ligas")]))

    # los traspasos de enero dejan jugadores en dos ligas; se les asigna
    # aquella con mas minutos. El perfil agrega las dos medias temporadas.
    liga = (por_partido.group_by(["player_id", "league"])
                       .agg(pl.col("m").sum().alias("m"))
                       .sort("m", descending=True)
                       .group_by("player_id").first()
                       .select(["player_id", "league"]))

    # club con mas minutos, para mostrarlo en la interfaz
    club = (por_partido.group_by(["player_id", "team"])
                       .agg(pl.col("m").sum().alias("m"))
                       .sort("m", descending=True)
                       .group_by("player_id").first()
                       .select(["player_id", "team"]))

    # posición más frecuente
    pos = (ev.filter(pl.col("position").is_not_null())
             .group_by(["player_id", "position"]).agg(pl.len().alias("n"))
             .sort("n", descending=True)
             .group_by("player_id").first()
             .select(["player_id", "position"]))

    conteos = (ev.group_by(["player_id", "type"]).agg(pl.len().alias("n"))
                 .pivot(on="type", index="player_id", values="n")
                 .fill_null(0))

    df = (minutos.join(liga, on="player_id")
                 .join(club, on="player_id")
                 .join(pos, on="player_id")
                 .join(conteos, on="player_id")
                 .join(derivadas(ev), on="player_id")
                 .join(posesion(ev), on="player_id"))

    presentes = [c for c in METRICAS if c in df.columns]
    print("métricas encontradas:", presentes)

    df = df.filter(pl.col("minutos") >= MIN_MINUTOS)

    # p90 de los volumenes, viejos y nuevos
    p90 = ([(pl.col(c) / pl.col("minutos") * 90).round(2).alias(f"{slug(c)}_p90")
            for c in presentes] +
           [(pl.col(c) / pl.col("minutos") * 90).round(2).alias(f"{c}_p90")
            for c in ("prog_pass", "prog_carry")])

    df = df.with_columns(p90).with_columns([
        ratio("_ok", "_n_pases", "pass_completion"),
        ratio("_ok_pres", "_n_pres", "pass_comp_pressure"),
        ratio("_adelante", "_n_pases", "pass_forward_share"),
        ratio("_largos", "_n_pases", "pass_long_share"),
        ratio("_ult_tercio", "_n_toques", "touch_final_third"),
        (pl.when((pl.col("_aer_gan") + pl.col("_aer_perd")) >= MIN_DENOM)
           .then(pl.col("_aer_gan") /
                 (pl.col("_aer_gan") + pl.col("_aer_perd")))
           .otherwise(None).round(4).alias("aerial_win")),
    ])

    ratios = RATIOS

    # los nulos se dejan tal cual: rellenarlos aqui usaria una mediana
    # contaminada por los 114 porteros, que vectors.py descarta despues.
    # El relleno pertenece a la poblacion que se va a rankear.
    huecos = {c: df[c].null_count() for c in ratios}
    print("nulos por denominador escaso:", {k: v for k, v in huecos.items() if v})

    df.write_parquet(SALIDA)

    print(df.shape)
    print(df.group_by("league").agg(pl.len().alias("n")).sort("league"))
    print("multiliga:", df.filter(pl.col("n_ligas") > 1).height)
    print(f"posesion: media {df['posesion'].mean():.4f} "
          f"(debe ser ~0.5), rango {df['posesion'].min():.3f}"
          f"-{df['posesion'].max():.3f}")
    print(df.select(ratios).describe())


if __name__ == "__main__":
    run()
