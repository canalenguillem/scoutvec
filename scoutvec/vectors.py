import polars as pl
from scoutvec.roles import POS2ROLE

FEATURES = ["pass_p90", "shot_p90", "dribble_p90", "pressure_p90",
            "carry_p90", "ball_receipt_p90", "duel_p90",
            "interception_p90", "clearance_p90"]


def run():
    d = pl.read_parquet("players.parquet")
    d = d.with_columns(
        pl.col("position").replace_strict(POS2ROLE, default=None).alias("role")
    )

    sin_rol = d.filter(pl.col("role").is_null())
    if len(sin_rol):
        print("SIN ROL:", sin_rol["position"].unique().to_list())

    d = d.filter(pl.col("role").is_not_null() & (pl.col("role") != "GK"))

    d = d.with_columns([
        (pl.col(f).rank("average") / pl.len()).round(4).alias(f"pct_{f}")
        for f in FEATURES
    ])

    pct = [f"pct_{f}" for f in FEATURES]
    d = d.with_columns(pl.concat_list(pct).alias("vector"))
    d.write_parquet("vectors.parquet")

    print(d.group_by("role").agg(pl.len().alias("n")).sort("role"))
    print(d.filter(pl.col("player").str.contains("Messi"))
           .select(["player", "role", "pct_dribble_p90", "pct_pass_p90"])
           .to_pandas().to_string())


if __name__ == "__main__":
    run()