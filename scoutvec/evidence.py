# scoutvec/evidence.py
"""Por que dos jugadores se parecen, en jugadas y no en numeros.

La similitud es un coseno entre vectores normalizados, asi que es una suma
de 17 terminos: la parte que aporta cada dimension es exacta, no atribuida a
posteriori. Esto coge las dimensiones que mas aportan y recupera del parquet
de eventos las jugadas concretas que las produjeron, para poder dibujarlas.
"""
import numpy as np
import polars as pl

from scoutvec.datasets import get
from scoutvec.similarity import load
from scoutvec.vectors import FEATURES

# Como se dibuja cada dimension. "flecha" necesita origen y destino;
# "punto" solo origen. Las dimensiones sin entrada aqui no son dibujables:
# un ratio de acierto no es una jugada, es una propiedad de muchas.
DIBUJO = {
    "pass_p90":          ("flecha", "Passes",              None),
    "prog_pass_p90":     ("flecha", "Progressive passes",  "prog_pass"),
    "carry_p90":         ("flecha", "Carries",             None),
    "prog_carry_p90":    ("flecha", "Progressive carries", "prog_carry"),
    "pass_long_share":   ("flecha", "Long passes",         "largos"),
    "pass_forward_share":("flecha", "Forward passes",      "adelante"),
    "pass_completion":   ("flecha", "Completed passes",    "completos"),
    "pass_comp_pressure":("flecha", "Passes under pressure", "presionados"),
    "shot_p90":          ("punto",  "Shots",               None),
    "dribble_p90":       ("punto",  "Take-ons",            None),
    "pressure_p90":      ("punto",  "Pressures",           None),
    "interception_p90":  ("punto",  "Interceptions",       None),
    "clearance_p90":     ("punto",  "Clearances",          None),
    "duel_p90":          ("punto",  "Duels",               None),
    "aerial_win":        ("punto",  "Aerial duels won",    "aereos"),
    "ball_receipt_p90":  ("punto",  "Ball receipts",       None),
    "touch_final_third": ("punto",  "Touches, final third", "ult_tercio"),
}

TIPO = {
    "pass_p90": "Pass", "prog_pass_p90": "Pass", "pass_long_share": "Pass",
    "pass_forward_share": "Pass", "pass_completion": "Pass",
    "pass_comp_pressure": "Pass", "carry_p90": "Carry",
    "prog_carry_p90": "Carry", "shot_p90": "Shot", "dribble_p90": "Dribble",
    "pressure_p90": "Pressure", "interception_p90": "Interception",
    "clearance_p90": "Clearance", "duel_p90": "Duel", "aerial_win": None,
    "ball_receipt_p90": "Ball Receipt*", "touch_final_third": None,
}

TOQUES = ["Pass", "Carry", "Ball Receipt*", "Shot", "Dribble"]
PROG_PASE, PROG_CARRY, PASE_LARGO = 10.0, 5.0, 30.0

MAX_EVENTOS = 400          # mas que esto es una mancha, no un mapa


def _dist(x, y):
    return ((120 - pl.col(x)) ** 2 + (40 - pl.col(y)) ** 2).sqrt()


def drivers(i, j, dataset=None):
    """Cuanto aporta cada dimension al coseno entre i y j. Suma 1."""
    e = load(dataset)
    term = e.V[i] * e.V[j]                 # el coseno es term.sum()
    total = term.sum()
    orden = np.argsort(-term)
    return [{"feature": FEATURES[k],
             "share": round(float(term[k] / total), 4),
             "a": round(float(e.P[i][k]), 4),
             "b": round(float(e.P[j][k]), 4),
             "drawable": FEATURES[k] in DIBUJO}
            for k in orden], float(total)


def _filtro(feature):
    """Condicion polars que aisla las jugadas de esta dimension."""
    avance = _dist("x", "y") - _dist("end_x", "end_y")
    tipo = TIPO.get(feature)
    cond = pl.col("type") == tipo if tipo else pl.lit(True)

    abierto = pl.col("pass_type").is_null()
    completo = pl.col("outcome").is_null()

    extra = {
        "prog_pass_p90":      abierto & completo & (avance >= PROG_PASE),
        "prog_carry_p90":     avance >= PROG_CARRY,
        "pass_long_share":    abierto & (pl.col("pass_len") >= PASE_LARGO),
        "pass_forward_share": abierto & (pl.col("end_x") > pl.col("x") + 2),
        "pass_completion":    abierto & completo,
        "pass_comp_pressure": abierto & pl.col("presion"),
        "pass_p90":           abierto,
    }.get(feature)
    if extra is not None:
        cond = cond & extra
    if feature == "aerial_win":
        cond = pl.col("aereo_ganado")
    if feature == "touch_final_third":
        cond = pl.col("type").is_in(TOQUES) & (pl.col("x") >= 80)
    return cond


def jugadas(player_id, feature, dataset=None, limite=MAX_EVENTOS):
    """Las jugadas de un jugador que producen esa dimension."""
    if feature not in DIBUJO:
        return []
    ds = get(dataset)
    if not ds.eventos.exists():
        raise FileNotFoundError(ds.eventos)

    forma = DIBUJO[feature][0]
    cols = ["x", "y"] + (["end_x", "end_y"] if forma == "flecha" else [])
    d = (pl.scan_parquet(ds.eventos)
           .filter((pl.col("player_id") == player_id) & _filtro(feature)
                   & pl.col("x").is_not_null())
           .select(cols).collect())

    if forma == "flecha":
        d = d.drop_nulls(["end_x", "end_y"])
    # muestreo determinista: el mapa debe ser el mismo en cada recarga
    if len(d) > limite:
        paso = len(d) / limite
        d = d[[int(k * paso) for k in range(limite)]]
    return d.rows(named=True)


def comparar(pid_a, pid_b, dataset=None, feature=None):
    """El paquete completo: contribuciones + las jugadas de la dominante."""
    e = load(dataset)
    i, j = e.ids.index(pid_a), e.ids.index(pid_b)
    ds, sim = drivers(i, j, dataset)

    if feature is None:
        feature = next((d["feature"] for d in ds if d["drawable"]), None)
    if feature is None:
        return {"sim": sim, "drivers": ds, "feature": None, "events": {}}

    forma, etiqueta, _ = DIBUJO[feature]
    return {
        "sim": round(sim, 4),
        "drivers": ds,
        "feature": feature,
        "shape": forma,
        "label": etiqueta,
        "events": {"a": jugadas(pid_a, feature, dataset),
                   "b": jugadas(pid_b, feature, dataset)},
    }
