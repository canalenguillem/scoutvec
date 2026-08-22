import argparse
from typing import NamedTuple

import numpy as np
import polars as pl

from scoutvec.roles import ROLES
from scoutvec.vectors import FEATURES

VECTORS = "vectors.parquet"

# FEATURES es el orden de las 17 dimensiones del vector, reexportado aqui
# para quien construya un perfil a mano: vec[i] corresponde a FEATURES[i].
DIMS = len(FEATURES)


class Espacio(NamedTuple):
    """El espacio vectorial cargado. Listas paralelas, indexadas igual que V."""
    ids: list        # player_id de StatsBomb
    names: list
    roles: list
    leagues: list
    teams: list
    minutes: list
    V: np.ndarray    # (n, 17) normalizada a norma 1, para el coseno
    P: np.ndarray    # (n, 17) percentiles sin normalizar, para los radares


_cache = None


def load(path=VECTORS):
    global _cache
    if _cache is None:
        d = pl.read_parquet(path)
        P = np.array(d["vector"].to_list())
        V = P / np.linalg.norm(P, axis=1, keepdims=True)
        _cache = Espacio(
            ids=d["player_id"].to_list(),
            names=d["player"].to_list(),
            roles=d["role"].to_list(),
            leagues=d["league"].to_list(),
            teams=d["team"].to_list(),
            minutes=d["minutos"].to_list(),
            V=V, P=P,
        )
    return _cache


def find(name):
    names = load().names
    hits = [i for i, n in enumerate(names) if name.lower() in n.lower()]
    if not hits:
        raise KeyError(f"sin coincidencia para {name!r}")
    if len(hits) > 1:
        otros = ", ".join(names[i] for i in hits[1:4])
        print(f"  aviso: {name!r} coincide con {len(hits)} "
              f"({names[hits[0]]}, {otros}...), uso el primero")
    return hits[0]


def _keep(role):
    if role is None:
        return None
    keep = {role} if isinstance(role, str) else set(role)
    malos = keep - set(ROLES)
    if malos:
        raise ValueError(f"rol desconocido: {sorted(malos)} "
                         f"— válidos: {sorted(ROLES)}")
    return keep


def vecinos(q, k, keep=None, salta=None):
    """Indices de los k mas cercanos a q, ya filtrados. El nucleo de todo."""
    e = load()
    s = e.V @ (q / np.linalg.norm(q))
    out = []
    for j in np.argsort(-s):
        if j == salta or (keep is not None and e.roles[j] not in keep):
            continue
        out.append((int(j), float(s[j])))
        if len(out) == k:
            break
    return out


def _rank(q, k, keep, salta=None):
    e = load()
    out = [(e.names[j], e.leagues[j], e.roles[j], round(s, 4))
           for j, s in vecinos(q, k, keep, salta)]
    return pl.DataFrame(out, schema=["player", "league", "role", "sim"],
                        orient="row")


def similar(name, k=8, role=None):
    keep = _keep(role)
    i = find(name)
    return _rank(load().V[i], k, keep, salta=i)


def target(vec, k=8, role=None):
    q = np.asarray(vec, dtype=float).ravel()
    if q.size != DIMS:
        raise ValueError(f"el perfil necesita {DIMS} dims en el orden "
                         f"{FEATURES}, recibidas {q.size}")
    if not np.isfinite(q).all():
        raise ValueError("el perfil tiene NaN o inf")
    if np.linalg.norm(q) == 0:
        raise ValueError("el perfil es todo ceros, el coseno no esta definido")
    fuera = [(FEATURES[i], v) for i, v in enumerate(q) if not 0 <= v <= 1]
    if fuera:
        print(f"  aviso: el espacio son percentiles en [0,1], fuera de rango: {fuera}")
    return _rank(q, k, _keep(role))


def similar_role(name, role=None, k=8):
    e = load()
    i = find(name)
    return _rank(e.V[i], k, _keep(role) or {e.roles[i]}, salta=i)


def show(name, k=8, role=None):
    e = load()
    keep = _keep(role)
    i = find(name)
    filtro = "" if keep is None else f"  [rol={'|'.join(sorted(keep))}]"
    print(f"\n~ {e.names[i]} ({e.leagues[i]}, {e.roles[i]}){filtro}")
    for p, lg, r, s in _rank(e.V[i], k, keep, salta=i).iter_rows():
        print(f"  {s:.3f}  {p:38s} ({lg}, {r})")


def show_target(vec, k=8, role=None, etiqueta="perfil"):
    filtro = "" if role is None else f"  [rol={role}]"
    print(f"\n~ {etiqueta} (target){filtro}")
    perfil = ", ".join(f"{f.removesuffix('_p90')}={v:.2f}"
                       for f, v in zip(FEATURES, vec))
    print(f"  {perfil}")
    for p, lg, r, s in target(vec, k=k, role=role).iter_rows():
        print(f"  {s:.3f}  {p:38s} ({lg}, {r})")


def perfil(**kw):
    """Construye el vector por nombre de metrica; lo no indicado va a 0.5."""
    malas = set(kw) - set(FEATURES)
    if malas:
        raise ValueError(f"metrica desconocida: {sorted(malas)} "
                         f"— validas: {FEATURES}")
    return [kw.get(f, 0.5) for f in FEATURES]


def run(consultas=("Messi", "Busquets", "Piqué"), k=8, role=None,
        mismo_rol=False):
    e = load()
    for q in consultas:
        show(q, k=k, role=e.roles[find(q)] if mismo_rol else role)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m scoutvec.similarity")
    ap.add_argument("players", nargs="*", default=["Messi", "Busquets", "Piqué"])
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--role", default=None, help=f"filtra: {'|'.join(ROLES)}")
    ap.add_argument("--same-role", action="store_true",
                    help="filtra por el rol del propio jugador")
    ap.add_argument("--target", default=None,
                    help=f"{DIMS} valores separados por coma, orden: "
                         f"{','.join(FEATURES)}")
    a = ap.parse_args()

    if a.target:
        vec = [float(x) for x in a.target.split(",")]
        show_target(vec, k=a.k, role=a.role)
    else:
        run(a.players, k=a.k, role=a.role, mismo_rol=a.same_role)
