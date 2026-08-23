# scoutvec/api.py
"""API de solo lectura.

MariaDB responde metadatos, listados y filtros; Qdrant responde vecinos.
Con SCOUTVEC_BACKEND=numpy usa vectors.parquet en memoria y no necesita
ningun servicio — que es como se desarrolla fuera de Docker.
"""
import os
from datetime import datetime, timezone

from fastapi import (Cookie, Depends, FastAPI, HTTPException, Query,
                     Request, Response)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scoutvec import auth
from scoutvec.datasets import DATASETS, POR_DEFECTO, disponibles
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


# ------------------------------------------------------------------ sesion
class Credenciales(BaseModel):
    username: str
    password: str


class CambioClave(BaseModel):
    current_password: str
    new_password: str


class Sesion(BaseModel):
    username: str
    must_change_password: bool


def _con():
    from scoutvec import store
    return store.conectar(reintentos=3, espera=1)


def sesion_actual(scoutvec_session: str | None = Cookie(default=None)):
    """Sesion valida o 401. Es la puerta de todos los endpoints de datos."""
    if not scoutvec_session:
        raise HTTPException(401, "no autenticado")
    con = _con(); cur = con.cursor()
    cur.execute(
        "SELECT u.id, u.username, u.must_change, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s", (auth.huella(scoutvec_session),))
    fila = cur.fetchone()
    con.close()
    if not fila:
        raise HTTPException(401, "sesion invalida")
    if fila[3] and fila[3].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(401, "sesion caducada")
    return {"id": fila[0], "username": fila[1], "must_change": bool(fila[2])}


def usuario(u=Depends(sesion_actual)):
    """Sesion valida Y con la clave ya cambiada.

    Separar las dos comprobaciones es lo que permite que un usuario con clave
    temporal pueda llamar a /auth/change-password y a nada mas.
    """
    if u["must_change"]:
        raise HTTPException(
            403, "debes cambiar la contraseña antes de usar la aplicacion")
    return u


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


class Pregunta(BaseModel):
    q: str = Field(description="consulta libre",
                   json_schema_extra={"example":
                       "un central que saque el balon jugado y gane de cabeza"})


class Ajuste(BaseModel):
    feature: str
    value: float
    why: str = Field(description="las palabras de la peticion que lo justifican")


class ConsultaEstructurada(BaseModel):
    adjustments: list[Ajuste]
    unsupported: str | None = Field(
        default=None,
        description="la peticion no se puede responder con estas 17 dimensiones")
    profile: dict[str, float] = Field(
        description="derivado de adjustments; lo no ajustado vale 0.5")
    role: str | None
    league: str | None
    k: int
    summary: str
    model: str
    prompt_version: str


class Respuesta(BaseModel):
    """La consulta estructurada viaja con los resultados: si los jugadores no
    convencen, se ve exactamente que se pidio. Eso es la explicabilidad."""
    query: ConsultaEstructurada
    results: list["Vecino"]


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
    """Los parquet en memoria. Sin servicios."""

    def __init__(self):
        from scoutvec import similarity as sim
        self.sim = sim
        self.ds = None

    def usar(self, slug):
        self.ds = slug
        self.e = self.sim.load(slug)
        return self

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
        for j, s in self.sim.vecinos(self.e.V[i], holgura, keep, salta=i,
                                     dataset=self.ds):
            if league and self.e.leagues[j] != league:
                continue
            out.append({**self._fila(j), "sim": round(s, 4)})
            if len(out) == k:
                break
        return out

    def restricciones(self, objetivos, k, keep, league=None):
        holgura = k if league is None else min(len(self.e.ids), k * 12)
        out = []
        for j, f in self.sim.por_restricciones(objetivos, holgura, keep,
                                               dataset=self.ds):
            if league and self.e.leagues[j] != league:
                continue
            out.append({**self._fila(j), "sim": round(f, 4)})
            if len(out) == k:
                break
        return out

    def objetivo(self, vec, k, keep, league=None):
        import numpy as np
        q = np.asarray(vec, dtype=float)
        # se pide de mas porque la liga se filtra despues del ranking
        holgura = k if league is None else min(len(self.e.ids), k * 12)
        out = []
        for j, s in self.sim.vecinos(q, holgura, keep, dataset=self.ds):
            if league and self.e.leagues[j] != league:
                continue
            out.append({**self._fila(j), "sim": round(s, 4)})
            if len(out) == k:
                break
        return out


class BackendStores:
    """MariaDB para metadatos y filtros, Qdrant para vecinos."""

    def __init__(self):
        from scoutvec import store
        self.store = store
        self.qc = store.qdrant()
        self.ds = POR_DEFECTO

    def usar(self, slug):
        self.ds = slug
        return self

    @property
    def coleccion(self):
        return DATASETS[self.ds].coleccion

    def _con(self):
        return self.store.conectar(reintentos=3, espera=1)

    @staticmethod
    def _fila(r):
        return {"id": r[0], "name": r[1], "team": r[2], "league": r[3],
                "role": r[4], "minutes": r[5]}

    def meta(self):
        con = self._con(); cur = con.cursor()
        cur.execute("SELECT DISTINCT role FROM players WHERE dataset=%s ORDER BY role", (self.ds,))
        roles = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT league FROM players WHERE dataset=%s ORDER BY league", (self.ds,))
        leagues = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT team FROM players WHERE dataset=%s ORDER BY team", (self.ds,))
        teams = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM players WHERE dataset=%s", (self.ds,))
        n = cur.fetchone()[0]
        con.close()
        return {"roles": roles, "leagues": leagues, "teams": teams, "players": n}

    def listar(self, q, league, role, team, limit, offset):
        cond, args = ["dataset = %s"], [self.ds]
        if q:
            cond.append("name LIKE %s"); args.append(f"%{q}%")
        if league:
            cond.append("league = %s"); args.append(league)
        if role:
            cond.append("role = %s"); args.append(role)
        if team:
            cond.append("team = %s"); args.append(team)
        where = f"WHERE {' AND '.join(cond)}"
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
                    "WHERE dataset = %s AND id = %s", (self.ds, pid))
        r = cur.fetchone(); con.close()
        if not r:
            raise HTTPException(404, f"jugador {pid} no esta en el espacio")
        return self._fila(r)

    def perfil(self, pid):
        cols = list(self.store.COLS.values())
        con = self._con(); cur = con.cursor()
        cur.execute(f"SELECT id,name,team,league,role,minutes,{','.join(cols)} "
                    f"FROM players WHERE dataset = %s AND id = %s",
                    (self.ds, pid))
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
                    f"WHERE dataset = %s AND id IN ({marca})",
                    (self.ds, *ids))
        por_id = {r[0]: self._fila(r) for r in cur.fetchall()}
        con.close()
        return [{**por_id[p.id], "sim": round(float(p.score), 4)}
                for p in puntos if p.id in por_id]

    def vecinos(self, pid, k, keep, league):
        self._uno(pid)                       # 404 si no existe
        res = self.qc.query_points(
            self.coleccion, query=pid, limit=k,
            query_filter=self._filtro(keep, league), with_payload=False).points
        return self._hidratar([p for p in res if p.id != pid][:k])

    def restricciones(self, objetivos, k, keep, league=None):
        """Ordenar por unas pocas columnas es exactamente lo que sabe hacer
        una base relacional; Qdrant aqui no aporta nada."""
        cols = self.store.COLS
        piezas = [(f"({cols[f]})" if v > 0.5 else f"(1 - {cols[f]})")
                  for f, v in objetivos.items() if f in cols]
        if not piezas:
            raise HTTPException(422, "ninguna dimension valida")
        fuerza = "(" + " + ".join(piezas) + f") / {len(piezas)}"

        cond, args = ["dataset = %s"], [self.ds]
        if keep:
            cond.append(f"role IN ({','.join(['%s'] * len(keep))})")
            args += sorted(keep)
        if league:
            cond.append("league = %s"); args.append(league)
        con = self._con(); cur = con.cursor()
        cur.execute(f"SELECT id,name,team,league,role,minutes, {fuerza} AS s "
                    f"FROM players WHERE {' AND '.join(cond)} "
                    f"ORDER BY s DESC LIMIT %s", (*args, k))
        out = [{**self._fila(r), "sim": round(float(r[6]), 4)}
               for r in cur.fetchall()]
        con.close()
        return out

    def objetivo(self, vec, k, keep, league=None):
        # aqui la liga entra en el filtro del indice, no despues
        res = self.qc.query_points(
            self.coleccion, query=list(map(float, vec)), limit=k,
            query_filter=self._filtro(keep, league), with_payload=False).points
        return self._hidratar(res)


_backend = None


def backend(dataset=None):
    global _backend
    if _backend is None:
        _backend = BackendNumpy() if BACKEND == "numpy" else BackendStores()
    return _backend.usar(_dataset(dataset))


def _dataset(slug: str | None) -> str:
    """Valida el dataset pedido contra los que estan realmente cargados."""
    listos = [d.slug for d in disponibles()] or [POR_DEFECTO]
    if slug is None:
        return POR_DEFECTO if POR_DEFECTO in listos else listos[0]
    if slug not in DATASETS:
        raise HTTPException(422, f"dataset {slug!r} desconocido, validos: "
                                 f"{list(DATASETS)}")
    return slug


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


@app.post("/auth/login", response_model=Sesion, summary="Iniciar sesion")
def login(c: Credenciales, resp: Response, request: Request):
    con = _con(); cur = con.cursor()
    cur.execute("SELECT id, password_hash, must_change FROM users "
                "WHERE username = %s", (c.username.strip(),))
    fila = cur.fetchone()

    # se verifica siempre, exista el usuario o no: si solo se verificara
    # cuando existe, el tiempo de respuesta revelaria que usuarios hay
    guardado = fila[1] if fila else auth.hashear("señuelo-para-igualar-tiempos")
    if not auth.verificar(c.password, guardado) or not fila:
        con.close()
        raise HTTPException(401, "usuario o contraseña incorrectos")

    token, hh = auth.nuevo_token()
    cur.execute("DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP()")
    cur.execute("INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)", (hh, fila[0], auth.caduca_en()))
    cur.execute("UPDATE users SET last_login = UTC_TIMESTAMP() WHERE id = %s",
                (fila[0],))
    con.commit(); con.close()

    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax",
                    secure=auth.cookie_segura(request),
                    max_age=auth.DIAS_SESION * 86400, path="/")
    return {"username": c.username.strip(), "must_change_password": bool(fila[2])}


@app.post("/auth/logout", summary="Cerrar sesion")
def logout(resp: Response, scoutvec_session: str | None = Cookie(default=None)):
    if scoutvec_session:
        con = _con(); cur = con.cursor()
        cur.execute("DELETE FROM sessions WHERE token_hash = %s",
                    (auth.huella(scoutvec_session),))
        con.commit(); con.close()
    resp.delete_cookie(auth.COOKIE, path="/")
    return {"status": "ok"}


@app.get("/auth/me", response_model=Sesion, summary="Quien soy")
def me(u=Depends(sesion_actual)):
    return {"username": u["username"], "must_change_password": u["must_change"]}


@app.post("/auth/change-password", response_model=Sesion,
          summary="Cambiar contraseña")
def change_password(c: CambioClave, resp: Response, request: Request,
                    u=Depends(sesion_actual),
                    scoutvec_session: str | None = Cookie(default=None)):
    """Accesible con la clave temporal aun sin cambiar: es su unica salida."""
    motivo = auth.politica(c.new_password)
    if motivo:
        raise HTTPException(422, motivo)
    if c.new_password == c.current_password:
        raise HTTPException(422, "la nueva contraseña debe ser distinta")

    con = _con(); cur = con.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (u["id"],))
    guardado = cur.fetchone()[0]
    if not auth.verificar(c.current_password, guardado):
        con.close()
        raise HTTPException(401, "la contraseña actual no es correcta")

    cur.execute("UPDATE users SET password_hash = %s, must_change = 0 "
                "WHERE id = %s", (auth.hashear(c.new_password), u["id"]))
    # cambiar la clave invalida las demas sesiones: si alguien mas la tenia,
    # se queda fuera
    cur.execute("DELETE FROM sessions WHERE user_id = %s", (u["id"],))
    token, hh = auth.nuevo_token()
    cur.execute("INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)", (hh, u["id"], auth.caduca_en()))
    con.commit(); con.close()

    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax",
                    secure=auth.cookie_segura(request),
                    max_age=auth.DIAS_SESION * 86400, path="/")
    return {"username": u["username"], "must_change_password": False}


@app.get("/meta", summary="Vocabulario del espacio")
def meta(dataset: str | None = None, _=Depends(usuario)):
    slug = _dataset(dataset)
    return {"features": FEATURES,
            "dataset": slug,
            "datasets": [{"slug": d.slug, "label": d.etiqueta,
                          "season": d.temporada, "note": d.nota,
                          "leagues": list(d.ligas)}
                         for d in disponibles()],
            **backend(slug).meta()}


@app.get("/players", response_model=list[Jugador], summary="Listar y filtrar")
def players(q: str | None = Query(None, description="subcadena del nombre"),
            league: str | None = None, role: str | None = None,
            team: str | None = None,
            limit: int = Query(50, ge=1, le=500),
            offset: int = Query(0, ge=0),
            dataset: str | None = None,
            _=Depends(usuario)):
    _rol(role)
    return backend(dataset).listar(q, league, role, team, limit, offset)


@app.get("/players/{player_id}", response_model=Perfil, summary="Un jugador")
def player(player_id: int, dataset: str | None = None, _=Depends(usuario)):
    return backend(dataset).perfil(player_id)


@app.get("/similar/{player_id}", response_model=list[Vecino],
         summary="Vecinos por coseno")
def similar(player_id: int, k: int = Query(8, ge=1, le=MAX_K),
            role: str | None = None,
            same_role: bool = Query(False, description="usa el rol del jugador"),
            league: str | None = None,
            dataset: str | None = None,
            _=Depends(usuario)):
    b = backend(dataset)
    keep = _rol(role)
    if same_role and not keep:
        keep = {b.perfil(player_id)["role"]}
    return b.vecinos(player_id, k, keep, league)


@app.post("/similar/target", response_model=list[Vecino],
          summary="Perfil a mano, sin jugador de referencia")
def similar_target(o: Objetivo, dataset: str | None = None,
                   _=Depends(usuario)):
    malas = set(o.profile) - set(FEATURES)
    if malas:
        raise HTTPException(422, f"metrica desconocida: {sorted(malas)}")
    if not 1 <= o.k <= MAX_K:
        raise HTTPException(422, f"k fuera de rango [1, {MAX_K}]")
    fuera = {f: v for f, v in o.profile.items() if not 0 <= v <= 1}
    if fuera:
        raise HTTPException(422, f"el espacio son percentiles en [0,1]: {fuera}")
    vec = [o.profile.get(f, 0.5) for f in FEATURES]
    return backend(dataset).objetivo(vec, o.k, _rol(o.role))


@app.post("/ask", response_model=Respuesta,
          summary="Consulta en lenguaje natural")
def ask(p: Pregunta, dataset: str | None = None, _=Depends(usuario)):
    """El modelo traduce a consulta estructurada; la busqueda la ejecuta
    el mismo codigo determinista que el resto de la API."""
    from scoutvec import nl

    if not p.q.strip():
        raise HTTPException(422, "la pregunta esta vacia")
    if len(p.q) > 500:
        raise HTTPException(422, "pregunta demasiado larga (max 500)")

    try:
        q = nl.traducir(p.q, dataset=_dataset(dataset))
    except nl.SinClave as e:
        raise HTTPException(503, str(e))
    except Exception as e:                      # noqa: BLE001
        raise HTTPException(502, f"el traductor fallo: {type(e).__name__}: {e}")

    # una peticion irrespondible se dice, no se contesta con lo mas parecido
    if q.get("unsupported"):
        return {"query": q, "results": []}

    if not q["adjustments"]:
        raise HTTPException(422, "no he sabido traducir eso a un perfil; "
                                 "prueba a describir como juega")

    objetivos = {a["feature"]: a["value"] for a in q["adjustments"]}
    res = backend(dataset).restricciones(objetivos, q["k"], _rol(q["role"]),
                                         q["league"])
    return {"query": q, "results": res}


class Driver(BaseModel):
    feature: str
    share: float = Field(description="fraccion exacta del coseno que aporta")
    a: float
    b: float
    drawable: bool


class Evidencia(BaseModel):
    sim: float
    drivers: list[Driver]
    feature: str | None = Field(description="dimension que ilustran los eventos")
    shape: str | None = None
    label: str | None = None
    events: dict[str, list[dict[str, float]]] = {}


@app.get("/evidence/{a_id}/{b_id}", response_model=Evidencia,
         summary="Por que se parecen, en jugadas")
def evidence(a_id: int, b_id: int, feature: str | None = None,
             dataset: str | None = None, _=Depends(usuario)):
    """Descompone el coseno y devuelve las jugadas de la dimension elegida.

    La descomposicion es exacta: con vectores normalizados el coseno es la
    suma de 17 productos, asi que el reparto no se estima.
    """
    from scoutvec import evidence as ev

    slug = _dataset(dataset)
    if feature is not None and feature not in ev.DIBUJO:
        raise HTTPException(422, f"dimension {feature!r} no dibujable; "
                                 f"validas: {sorted(ev.DIBUJO)}")
    try:
        return ev.comparar(a_id, b_id, slug, feature)
    except ValueError:
        raise HTTPException(404, "algun jugador no esta en este dataset")
    except FileNotFoundError as e:
        # el parquet de eventos no viaja en la imagen: son 59 MiB de datos
        # derivados que se regeneran con el pipeline
        raise HTTPException(503, f"faltan los eventos ({e}); ejecuta "
                                 f"python -m scoutvec.ingest -d {slug}")


@app.get("/compare", response_model=list[Perfil], summary="Perfiles lado a lado")
def compare(ids: str = Query(description="player_id separados por coma"),
            dataset: str | None = None, _=Depends(usuario)):
    try:
        pedidos = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "ids debe ser una lista de enteros")
    if not 1 <= len(pedidos) <= 6:
        raise HTTPException(422, "entre 1 y 6 jugadores")
    b = backend(dataset)
    return [b.perfil(p) for p in pedidos]
