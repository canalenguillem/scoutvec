# scoutvec/features.py
import polars as pl

MIN_MINUTOS = 600

METRICAS = ["Pass", "Shot", "Dribble", "Pressure", "Carry",
            "Ball Receipt*", "Duel", "Interception", "Clearance"]


def slug(c):
    return c.lower().replace(" ", "_").replace("*", "")


def run():
    ev = pl.read_parquet("data/events.parquet")

    # minutos ≈ (último - primer evento) por jugador y partido
    minutos = (ev.group_by(["player_id", "player", "match_id"])
                 .agg((pl.col("minute").max() - pl.col("minute").min()).alias("m"))
                 .group_by(["player_id", "player"])
                 .agg([pl.col("m").sum().alias("minutos"),
                       pl.len().alias("partidos")]))

    # posición más frecuente
    pos = (ev.filter(pl.col("position").is_not_null())
             .group_by(["player_id", "position"]).agg(pl.len().alias("n"))
             .sort("n", descending=True)
             .group_by("player_id").first()
             .select(["player_id", "position"]))

    conteos = (ev.group_by(["player_id", "type"]).agg(pl.len().alias("n"))
                 .pivot(on="type", index="player_id", values="n")
                 .fill_null(0))

    df = minutos.join(pos, on="player_id").join(conteos, on="player_id")

    presentes = [c for c in METRICAS if c in df.columns]
    print("métricas encontradas:", presentes)

    df = (df.filter(pl.col("minutos") >= MIN_MINUTOS)
            .with_columns([(pl.col(c) / pl.col("minutos") * 90)
                           .round(2).alias(f"{slug(c)}_p90")
                           for c in presentes]))

    df.write_parquet("players.parquet")
    print(df.shape)
    print(df.sort("dribble_p90", descending=True)
            .select(["player", "position", "minutos", "dribble_p90", "pass_p90"])
            .head(15))


if __name__ == "__main__":
    run()