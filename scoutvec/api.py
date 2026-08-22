# scoutvec/api.py
"""API de solo lectura.

MariaDB responde metadatos, listados y filtros; Qdrant responde vecinos.
Con SCOUTVEC_BACKEND=numpy usa vectors.parquet en memoria y no necesita
ningun servicio — que es como se desarrolla fuera de Docker.
"""
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scoutvec.roles import ROLES
from scoutvec.vectors import FEATURES

BACKEND = os.getenv("SCOUTVEC_BACKEND", "stores")   # "stores" | "numpy"
MAX_K = 50

app = FastAPI(
    title="scoutvec",
    description="Busqueda de jugadores por similitud de estilo de juego.",
    version="0.5.0",
)

# en Docker el frontend habla por el proxy de nginx y no hace falta CORS;
# esto es para levantar Vite contra un backend suelto
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180", "http://127.0.0.1:5180"],
    allow_methods=["GET", "POST"], allow_headers=["*"],
)


class Jugador(BaseModel):
    id: int
    name: str
    team: str
    league: str
    role: str
    minutes: int


class Perfil(Jugador):
    vector: dict[str, float] = Field(
        description="percentil [0,1] por metrica, en el orden de FEATURES")


class Vecino(Jugador):
    sim: float


class Objetivo(BaseModel):
    profile: dict[str, float] = Field(
        default_factory=dict,
        json_schema_extra={"example": {"shot_p90": 0.97,
                                       "touch_final_third": 0.95,
                                       "interception_p90": 0.05}})
    k: int = 8
    role: str | None = None


# ---------------------------------------------------------------- backends
class BackendNumpy:
    """vectors.parquet en memoria. Sin servicios."""

    def __init__(self):
        from scoutvec import similarity as sim
        self.sim = sim
        self.e = sim.load(os.getenv("VECTORS_PATH", "vectors.parquet"))

    def _fila(self, i):
        e = self.e
        return {"id": e.ids[i], "name": e.names[i], "team": e.teams[i],
                "league": e.leagues[i], "role": e.roles[i],
                "minutes": e.minutes[i]}

    def meta(self):
        e = self.e
        return {"roles": sorted(set(e.roles)), "leagues": sorted(set(e.leagues)),
                "teams": sorted(set(e.teams)), "players": len(e.ids)}

    def listar(self, q, league, role, team, limit, offset):
        e = self.e
        idx = range(len(e.ids))
        if q:
            ql = q.lower()
            idx = [i for i in idx if ql in e.names[i].lower()]
        if league:
            idx = [i for i in idx if e.leagues[i] == league]
        if role:
            idx = [i for i in idx if e.roles[i] == role]
        if team:
            idx = [i for i in idx if e.teams[i] == team]
        idx = sorted(idx, key=lambda i: -e.minutes[i])
        return [self._fila(i) for i in idx[offset:offset + limit]]

    def _indice(self, pid):
        try:
            return self.e.ids.index(pid)
        except ValueError:
            raise HTTPException(404, f"jugador {pid} no esta en el espacio")

    def perfil(self, pid):
        i = self._indice(pid)
        return {**self._fila(i),
                "vector": {f: round(float(v), 4)
                           for f, v in zip(FEATURES, self.e.P[i])}}

    def vecinos(self, pid, k, keep, league):
        i = self._indice(pid)
        holgura = k if league is None else min(len(self.e.ids) - 1, k * 12)
        out = []
        for j, s in self.sim.vecinos(self.e.V[i], holgura, keep, salta=i):
            if league and self.e.leagues[j] != league:
                continue
            out.append({**self._fila(j), "sim": round(s, 4)})
            if len(out) == k:
                break
        return out

    def objetivo(self, vec, k, keep):
        import numpy as np
        q = np.asarray(vec, dtype=float)
        return [{**self._fila(j), "sim": round(s, 4)}
                for j, s in self.sim.vecinos(q, k, keep)]


class BackendStores:
    """MariaDB para metadatos y filtros, Qdrant para vecinos."""

    def __init__(self):
        from scoutvec import store
        self.store = store
        self.qc = store.qdrant()

    def _con(self):
        return self.store.conectar(reintentos=3, espera=1)

    @staticmethod
    def _fila(r):
        return {"id": r[0], "name": r[1], "team": r[2], "league": r[3],
                "role": r[4], "minutes": r[5]}

    def meta(self):
        con = self._con(); cur = con.cursor()
        cur.execute("SELECT DISTINCT role FROM players ORDER BY role")
        roles = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT league FROM players ORDER BY league")
        leagues = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT team FROM players ORDER BY team")
        teams = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM players")
        n = cur.fetchone()[0]
        con.close()
        return {"roles": roles, "leagues": leagues, "teams": teams, "players": n}

    def listar(self, q, league, role, team, limit, offset):
        cond, args = [], []
        if q:
            cond.append("name LIKE %s"); args.append(f"%{q}%")
        if league:
            cond.append("league = %s"); args.append(league)
        if role:
            cond.append("role = %s"); args.append(role)
        if team:
            cond.append("team = %s"); args.append(team)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        con = self._con(); cur = con.cursor()
        cur.execute(f"SELECT id,name,team,league,role,minutes FROM players "
                    f"{where} ORDER BY minutes DESC LIMIT %s OFFSET %s",
                    (*args, limit, offset))
        out = [self._fila(r) for r in cur.fetchall()]
        con.close()
        return out

    def _uno(self, pid):
        con = self._con(); cur = con.cursor()
        cur.execute("SELECT id,name,team,league,role,minutes FROM players "
                    "WHERE id = %s", (pid,))
        r = cur.fetchone(); con.close()
        if not r:
            raise HTTPException(404, f"jugador {pid} no esta en el espacio")
        return self._fila(r)

    def perfil(self, pid):
        cols = list(self.store.COLS.values())
        con = self._con(); cur = con.cursor()
        cur.execute(f"SELECT id,name,team,league,role,minutes,{','.join(cols)} "
                    f"FROM players WHERE id = %s", (pid,))
        r = cur.fetchone(); con.close()
        if not r:
            raise HTTPException(404, f"jugador {pid} no esta en el espacio")
        return {**self._fila(r),
                "vector": {f: float(v) for f, v in zip(FEATURES, r[6:])}}

    def _filtro(self, keep, league):
        from qdrant_client import models
        must = []
        if keep:
            must.append(models.FieldCondition(
                key="role", match=models.MatchAny(any=sorted(keep))))
        if league:
            must.append(models.FieldCondition(
                key="league", match=models.MatchValue(value=league)))
        return models.Filter(must=must) if must else None

    def _hidratar(self, puntos):
        """Qdrant devuelve id y score; los metadatos los pone MariaDB."""
        if not puntos:
            return []
        ids = [p.id for p in puntos]
        marca = ",".join(["%s"] * len(ids))
        con = self._con(); cur = con.cursor()
        cur.execute(f"SELECT id,name,team,league,role,minutes FROM players "
                    f"WHERE id IN ({marca})", tuple(ids))
        por_id = {r[0]: self._fila(r) for r in cur.fetchall()}
        con.close()
        return [{**por_id[p.id], "sim": round(float(p.score), 4)}
                for p in puntos if p.id in por_id]

    def vecinos(self, pid, k, keep, league):
        self._uno(pid)                       # 404 si no existe
        res = self.qc.query_points(
            self.store.COLECCION, query=pid, limit=k,
            query_filter=self._filtro(keep, league), with_payload=False).points
        return self._hidratar([p for p in res if p.id != pid][:k])

    def objetivo(self, vec, k, keep):
        res = self.qc.query_points(
            self.store.COLECCION, query=list(map(float, vec)), limit=k,
            query_filter=self._filtro(keep, None), with_payload=False).points
        return self._hidratar(res)


_backend = None


def backend():
    global _backend
    if _backend is None:
        _backend = BackendNumpy() if BACKEND == "numpy" else BackendStores()
    return _backend


def _rol(role):
    if role is not None and role not in ROLES:
        raise HTTPException(422, f"rol {role!r} desconocido, validos: "
                                 f"{sorted(ROLES)}")
    return {role} if role else None


# ---------------------------------------------------------------- endpoints
@app.get("/health", summary="Vivo y con datos")
def health():
    try:
        n = backend().meta()["players"]
    except Exception as e:                      # noqa: BLE001
        raise HTTPException(503, f"almacenes no listos: {e}")
    if not n:
        raise HTTPException(503, "almacenes vacios: falta sembrar")
    return {"status": "ok", "backend": BACKEND, "players": n}


@app.get("/meta", summary="Vocabulario del espacio")
def meta():
    return {"features": FEATURES, **backend().meta()}


@app.get("/players", response_model=list[Jugador], summary="Listar y filtrar")
def players(q: str | None = Query(None, description="subcadena del nombre"),
            league: str | None = None, role: str | None = None,
            team: str | None = None,
            limit: int = Query(50, ge=1, le=500),
            offset: int = Query(0, ge=0)):
    _rol(role)
    return backend().listar(q, league, role, team, limit, offset)


@app.get("/players/{player_id}", response_model=Perfil, summary="Un jugador")
def player(player_id: int):
    return backend().perfil(player_id)


@app.get("/similar/{player_id}", response_model=list[Vecino],
         summary="Vecinos por coseno")
def similar(player_id: int, k: int = Query(8, ge=1, le=MAX_K),
            role: str | None = None,
            same_role: bool = Query(False, description="usa el rol del jugador"),
            league: str | None = None):
    b = backend()
    keep = _rol(role)
    if same_role and not keep:
        keep = {b.perfil(player_id)["role"]}
    return b.vecinos(player_id, k, keep, league)


@app.post("/similar/target", response_model=list[Vecino],
          summary="Perfil a mano, sin jugador de referencia")
def similar_target(o: Objetivo):
    malas = set(o.profile) - set(FEATURES)
    if malas:
        raise HTTPException(422, f"metrica desconocida: {sorted(malas)}")
    if not 1 <= o.k <= MAX_K:
        raise HTTPException(422, f"k fuera de rango [1, {MAX_K}]")
    fuera = {f: v for f, v in o.profile.items() if not 0 <= v <= 1}
    if fuera:
        raise HTTPException(422, f"el espacio son percentiles en [0,1]: {fuera}")
    vec = [o.profile.get(f, 0.5) for f in FEATURES]
    return backend().objetivo(vec, o.k, _rol(o.role))


@app.get("/compare", response_model=list[Perfil], summary="Perfiles lado a lado")
def compare(ids: str = Query(description="player_id separados por coma")):
    try:
        pedidos = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "ids debe ser una lista de enteros")
    if not 1 <= len(pedidos) <= 6:
        raise HTTPException(422, "entre 1 y 6 jugadores")
    return [backend().perfil(p) for p in pedidos]
