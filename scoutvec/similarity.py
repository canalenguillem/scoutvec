import argparse
from typing import NamedTuple

import numpy as np
import polars as pl

from scoutvec.datasets import DATASETS, POR_DEFECTO, get
from scoutvec.roles import ROLES
from scoutvec.vectors import FEATURES

# FEATURES es el orden de las 17 dimensiones del vector, reexportado aqui
# para quien construya un perfil a mano: vec[i] corresponde a FEATURES[i].
DIMS = len(FEATURES)


class Espacio(NamedTuple):
    """El espacio vectorial cargado. Listas paralelas, indexadas igual que V."""
    slug: str        # de que dataset salio
    ids: list        # player_id de StatsBomb
    names: list
    roles: list
    leagues: list
    teams: list
    minutes: list
    V: np.ndarray    # (n, 17) normalizada a norma 1, para el coseno
    P: np.ndarray    # (n, 17) percentiles sin normalizar, para los radares


# un espacio por dataset: los percentiles de cada uno se calcularon sobre
# poblaciones distintas y no son intercambiables
_cache: dict[str, "Espacio"] = {}


def load(dataset=None):
    ds = get(dataset)
    if ds.slug not in _cache:
        if not ds.vectores.exists():
            raise SystemExit(f"falta {ds.vectores}: ejecuta el pipeline con "
                             f"-d {ds.slug}")
        d = pl.read_parquet(ds.vectores)
        P = np.array(d["vector"].to_list())
        V = P / np.linalg.norm(P, axis=1, keepdims=True)
        _cache[ds.slug] = Espacio(
            slug=ds.slug,
            ids=d["player_id"].to_list(),
            names=d["player"].to_list(),
            roles=d["role"].to_list(),
            leagues=d["league"].to_list(),
            teams=d["team"].to_list(),
            minutes=d["minutos"].to_list(),
            V=V, P=P,
        )
    return _cache[ds.slug]


def find(name, dataset=None):
    names = load(dataset).names
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


def vecinos(q, k, keep=None, salta=None, dataset=None):
    """Indices de los k mas cercanos a q, ya filtrados. El nucleo de todo."""
    e = load(dataset)
    s = e.V @ (q / np.linalg.norm(q))
    out = []
    for j in np.argsort(-s):
        if j == salta or (keep is not None and e.roles[j] not in keep):
            continue
        out.append((int(j), float(s[j])))
        if len(out) == k:
            break
    return out


def por_restricciones(objetivos, k, keep=None, dataset=None):
    """Ordena por las dimensiones que se pidieron, y solo por esas.

    El coseno contra un perfil de 17 dimensiones con 15 en 0.5 no sirve para
    una peticion parcial: esas 15 aportan el 79% de la norma, asi que el
    ranking acaba midiendo "quien es mas normal en general" en vez de lo que
    se pregunto. Medido: para "pase alto y sereno bajo presion" devolvia una
    central con percentil 0.41 de acierto de pase.

    Aqui el objetivo solo marca la DIRECCION. Un objetivo por encima de 0.5
    significa "cuanto mas alto mejor"; por debajo, "cuanto mas bajo mejor".
    Se puntua la media de la intensidad en esa direccion.
    """
    e = load(dataset)
    idx = [(FEATURES.index(f), v) for f, v in objetivos.items() if f in FEATURES]
    if not idx:
        raise ValueError("no hay ninguna dimension que ordenar")

    cols = np.array([j for j, _ in idx])
    sube = np.array([v > 0.5 for _, v in idx])
    P = e.P[:, cols]
    fuerza = np.where(sube, P, 1 - P).mean(axis=1)

    orden = np.argsort(-fuerza)
    out = []
    for j in orden:
        if keep is not None and e.roles[j] not in keep:
            continue
        out.append((int(j), float(fuerza[j])))
        if len(out) == k:
            break
    return out


def _rank(q, k, keep, salta=None, dataset=None):
    e = load(dataset)
    out = [(e.names[j], e.leagues[j], e.roles[j], round(s, 4))
           for j, s in vecinos(q, k, keep, salta, dataset)]
    return pl.DataFrame(out, schema=["player", "league", "role", "sim"],
                        orient="row")


def similar(name, k=8, role=None, dataset=None):
    keep = _keep(role)
    i = find(name, dataset)
    return _rank(load(dataset).V[i], k, keep, salta=i, dataset=dataset)


def target(vec, k=8, role=None, dataset=None):
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
    return _rank(q, k, _keep(role), dataset=dataset)


def similar_role(name, role=None, k=8, dataset=None):
    e = load(dataset)
    i = find(name, dataset)
    return _rank(e.V[i], k, _keep(role) or {e.roles[i]}, salta=i,
                 dataset=dataset)


def show(name, k=8, role=None, dataset=None):
    e = load(dataset)
    keep = _keep(role)
    i = find(name, dataset)
    filtro = "" if keep is None else f"  [rol={'|'.join(sorted(keep))}]"
    print(f"\n~ {e.names[i]} ({e.leagues[i]}, {e.roles[i]}){filtro}")
    for p, lg, r, s in _rank(e.V[i], k, keep, salta=i,
                             dataset=dataset).iter_rows():
        print(f"  {s:.3f}  {p:38s} ({lg}, {r})")


def show_target(vec, k=8, role=None, etiqueta="perfil", dataset=None):
    filtro = "" if role is None else f"  [rol={role}]"
    print(f"\n~ {etiqueta} (target){filtro}")
    perfil = ", ".join(f"{f.removesuffix('_p90')}={v:.2f}"
                       for f, v in zip(FEATURES, vec))
    print(f"  {perfil}")
    for p, lg, r, s in target(vec, k=k, role=role,
                              dataset=dataset).iter_rows():
        print(f"  {s:.3f}  {p:38s} ({lg}, {r})")


def perfil(**kw):
    """Construye el vector por nombre de metrica; lo no indicado va a 0.5."""
    malas = set(kw) - set(FEATURES)
    if malas:
        raise ValueError(f"metrica desconocida: {sorted(malas)} "
                         f"— validas: {FEATURES}")
    return [kw.get(f, 0.5) for f in FEATURES]


DEMO = {"men-2015-16": ("Messi", "Busquets", "Piqué"),
        "women-2023-24": ("Patricia Guijarro", "Williamson", "Graham Hansen")}


def run(consultas=None, k=8, role=None, mismo_rol=False, dataset=None):
    ds = get(dataset)
    e = load(dataset)
    for q in consultas or DEMO.get(ds.slug, ()):
        show(q, k=k, role=e.roles[find(q, dataset)] if mismo_rol else role,
             dataset=dataset)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m scoutvec.similarity")
    ap.add_argument("players", nargs="*", default=None)
    ap.add_argument("-d", "--dataset", default=POR_DEFECTO, choices=list(DATASETS))
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
        show_target(vec, k=a.k, role=a.role, dataset=a.dataset)
    else:
        run(a.players or None, k=a.k, role=a.role, mismo_rol=a.same_role,
            dataset=a.dataset)
