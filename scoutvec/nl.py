# scoutvec/nl.py
"""Consulta en lenguaje natural -> consulta estructurada.

El modelo NO responde quien se parece a quien. Traduce la pregunta a un
perfil de 17 percentiles mas filtros, y la busqueda vectorial —determinista,
verificable, la misma que usa el resto de la API— la ejecuta. Por eso la
respuesta devuelve la consulta estructurada junto a los resultados: si los
jugadores no convencen, se ve exactamente que se pidio.
"""
import json
import os

from scoutvec.roles import ROLES
from scoutvec.vectors import FEATURES

MODELO = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
VERSION = os.getenv("OPENAI_PROMPT_VERSION", "v1")

def ligas_de(dataset=None):
    from scoutvec.datasets import get
    return list(get(dataset).ligas)


LIGAS = ligas_de()
ROLES_VALIDOS = [r for r in ROLES if r != "GK"]

# que mide cada dimension, en el lenguaje del dominio. Sin esto el modelo
# adivina por el nombre de la columna y confunde volumen con acierto.
GLOSARIO = {
    "pass_p90":           "passes attempted per 90",
    "shot_p90":           "shots per 90",
    "dribble_p90":        "take-ons attempted per 90",
    "pressure_p90":       "pressing actions per 90",
    "carry_p90":          "ball carries per 90",
    "ball_receipt_p90":   "passes received per 90 — how often team-mates find them",
    "duel_p90":           "duels contested per 90",
    "interception_p90":   "interceptions per 90 — reading the game, not tackling",
    "clearance_p90":      "clearances per 90 — hoofing danger away",
    "prog_pass_p90":      "progressive passes per 90 — passes moving the ball 10+ yards closer to goal",
    "prog_carry_p90":     "progressive carries per 90 — driving with the ball",
    "pass_completion":    "share of open-play passes completed overall",
    "pass_comp_pressure": "pass completion WHILE UNDER PRESSURE — use this one "
                          "for 'does not lose the ball when pressed', 'composed "
                          "in tight spaces'",
    "pass_forward_share": "share of passes played forward — vertical vs sideways",
    "pass_long_share":    "share of passes 30+ yards — direct vs short",
    "touch_final_third":  "share of touches in the attacking third — how high they play",
    "aerial_win":         "share of aerial duels won",
}

SISTEMA = f"""You translate a football scouting request into a structured query \
over a vector space of 1,419 outfield players (La Liga, Premier League, \
Serie A, Ligue 1, 2015/16).

Every dimension is a GLOBAL PERCENTILE in [0,1] across all 1,419 players, \
already adjusted for how much possession the player's team has. 0.5 is exactly \
average, 0.9 is top 10%, 0.1 is bottom 10%.

The 17 dimensions:
{chr(10).join(f"- {f}: {d}" for f, d in GLOSARIO.items())}

Rules:
- List ONLY the dimensions the request actually implies, in `adjustments`. \
Everything you do not list stays at 0.5. A profile where everything is extreme \
matches nobody. Two to five adjustments is usually right.
- Every adjustment needs a `why`: the words in the request that justify it. If \
you cannot point at something in the request, do not adjust that dimension.
- Distinguish volume from quality. "Passes a lot" is pass_p90; "rarely gives \
it away" is pass_completion; "keeps it under pressure" is pass_comp_pressure. \
Those are three different players.
- Use `role` only when the request names a position. The vector already \
encodes playing style, so filtering by role is a narrowing, not the mechanism.
- Use `league` only when the request names a competition.
- `k` is how many players to return: default 8, honour an explicit number, cap 50.
- `summary` is one short sentence in the language of the request. It must \
describe exactly the adjustments you listed and nothing else."""


def esquema(ligas=None):
    """JSON Schema strict.

    El modelo enumera AJUSTES, no un perfil completo. El perfil se construye
    a partir de ellos, asi que el texto no puede describir un movimiento que
    no ocurrio: no hay dos fuentes de verdad que puedan discrepar.
    """
    return {
        "type": "object",
        "properties": {
            "adjustments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string", "enum": list(FEATURES)},
                        "value": {"type": "number"},
                        "why": {"type": "string",
                                "description": "las palabras de la peticion "
                                               "que justifican este ajuste"},
                    },
                    "required": ["feature", "value", "why"],
                    "additionalProperties": False,
                },
            },
            "role": {"type": ["string", "null"], "enum": [*ROLES_VALIDOS, None]},
            "league": {"type": ["string", "null"],
                       "enum": [*(ligas or LIGAS), None]},
            "k": {"type": "integer"},
            "summary": {"type": "string"},
        },
        "required": ["adjustments", "role", "league", "k", "summary"],
        "additionalProperties": False,
    }


class SinClave(RuntimeError):
    pass


def cliente():
    clave = os.getenv("OPENAI_API_KEY", "").strip()
    if not clave:
        raise SinClave("falta OPENAI_API_KEY: copia .env.example a .env")
    from openai import OpenAI
    return OpenAI(api_key=clave)


def sanear(bruto, ligas=None):
    """Convierte la salida del modelo en la consulta que se ejecuta.

    El perfil se DERIVA de los ajustes: lo no ajustado vale 0.5. Los ajustes
    invalidos se descartan aqui y no en el prompt, porque un prompt no es un
    contrato.
    """
    ajustes, vistas = [], set()
    for aj in bruto.get("adjustments") or []:
        f = aj.get("feature")
        if f not in FEATURES or f in vistas:
            continue                       # desconocida o repetida
        vistas.add(f)
        ajustes.append({"feature": f,
                        "value": min(1.0, max(0.0, float(aj.get("value", 0.5)))),
                        "why": str(aj.get("why", ""))[:200]})

    perfil = dict.fromkeys(FEATURES, 0.5)
    for aj in ajustes:
        perfil[aj["feature"]] = aj["value"]

    role = bruto.get("role")
    ligas = ligas or LIGAS
    league = bruto.get("league")
    return {
        "adjustments": ajustes,
        "profile": perfil,
        "role": role if role in ROLES_VALIDOS else None,
        "league": league if league in ligas else None,
        "k": max(1, min(50, int(bruto.get("k") or 8))),
        "summary": str(bruto.get("summary", ""))[:400],
    }


def traducir(pregunta, cli=None, dataset=None):
    """Devuelve la consulta estructurada. `cli` se inyecta en los tests."""
    if not (pregunta or "").strip():
        raise ValueError("la pregunta esta vacia")

    ligas = ligas_de(dataset)
    cli = cli or cliente()
    r = cli.chat.completions.create(
        model=MODELO,
        temperature=0,
        messages=[{"role": "system", "content": SISTEMA},
                  {"role": "user", "content": pregunta.strip()}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "scout_query", "strict": True,
                            "schema": esquema(ligas)},
        },
    )
    q = sanear(json.loads(r.choices[0].message.content), ligas)
    q["model"] = MODELO
    q["prompt_version"] = VERSION
    return q
