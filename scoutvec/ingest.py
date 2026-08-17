# scoutvec/ingest.py
import polars as pl
from tqdm import tqdm

from scoutvec.fetch import matches, events

COMP, SEASON = 11, 27  # La Liga 2015/16

SCHEMA = {
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
    "xg": pl.Float64,
    "outcome": pl.String,
}


def flatten(e, match_id):
    """Un evento anidado de StatsBomb → una fila plana. None si no hay jugador."""
    p = e.get("player")
    if p is None:  # Half Start, Starting XI, Tactical Shift...
        return None
    loc = e.get("location") or [None, None]
    return {
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
        "xg": (e.get("shot") or {}).get("statsbomb_xg"),
        "outcome": ((e.get("pass") or e.get("dribble") or {})
                    .get("outcome") or {}).get("name"),
    }


def run():
    ms = matches(COMP, SEASON)
    rows = []
    for m in tqdm(ms):
        for e in events(m["match_id"]):
            r = flatten(e, m["match_id"])
            if r:
                rows.append(r)

    df = pl.DataFrame(rows, schema=SCHEMA)
    df.write_parquet("data/events.parquet")
    print(df.shape)
    print(df.head())


if __name__ == "__main__":
    run()