#!/usr/bin/env python3
"""Tests de la capa de lenguaje natural que NO llaman a OpenAI.

Todo lo que puede ir mal con una salida de modelo se prueba aqui: es
determinista, no cuesta dinero y corre sin clave. La llamada real se prueba
aparte, a mano.
"""
import sys

from scoutvec.nl import FEATURES, sanear, traducir

ok = fallos = 0


def comprueba(nombre, real, esperado):
    global ok, fallos
    if real == esperado:
        ok += 1
        print(f"  PASA  {nombre}")
    else:
        fallos += 1
        print(f"  FALLA {nombre}\n        esperado {esperado!r}\n        obtuve   {real!r}")


def movidas(q):
    return {f: v for f, v in q["profile"].items() if v != 0.5}


# --- el perfil se deriva de los ajustes ------------------------------------
q = sanear({"adjustments": [{"feature": "shot_p90", "value": 0.9, "why": "x"}],
            "role": "FW", "league": None, "k": 8, "summary": "s"})
comprueba("lo no ajustado vale 0.5", movidas(q), {"shot_p90": 0.9})
comprueba("el perfil trae las 17 dimensiones", len(q["profile"]), len(FEATURES))

# --- saneado de basura -----------------------------------------------------
q = sanear({"adjustments": [
    {"feature": "goles", "value": 0.9, "why": "no existe"},
    {"feature": "shot_p90", "value": 4.2, "why": "fuera de rango"},
    {"feature": "shot_p90", "value": 0.1, "why": "repetida"},
], "role": "PORTERO", "league": "Bundesliga", "k": 999, "summary": "s"})
comprueba("descarta metrica inventada", "goles" in q["profile"], False)
comprueba("recorta valor fuera de [0,1]", q["profile"]["shot_p90"], 1.0)
comprueba("ignora ajuste repetido", len(q["adjustments"]), 1)
comprueba("descarta rol invalido", q["role"], None)
comprueba("descarta liga invalida", q["league"], None)
comprueba("recorta k al maximo", q["k"], 50)

comprueba("k ausente -> 8", sanear({"adjustments": []})["k"], 8)
comprueba("k cero -> 8", sanear({"adjustments": [], "k": 0})["k"], 8)
comprueba("sin ajustes -> perfil neutro", movidas(sanear({"adjustments": []})), {})
comprueba("adjustments nulo no revienta", movidas(sanear({"adjustments": None})), {})

# --- la garantia que hace fiable la explicacion -----------------------------
q = sanear({"adjustments": [
    {"feature": "aerial_win", "value": 0.7, "why": "gane de cabeza"},
    {"feature": "prog_pass_p90", "value": 0.7, "why": "saque el balon"},
], "role": "CB", "league": None, "k": 8, "summary": "s"})
comprueba("perfil y ajustes no pueden discrepar",
          movidas(q), {a["feature"]: a["value"] for a in q["adjustments"]})

# --- pregunta vacia ---------------------------------------------------------
try:
    traducir("   ")
    comprueba("pregunta vacia levanta ValueError", "no levanto", "ValueError")
except ValueError:
    comprueba("pregunta vacia levanta ValueError", "ValueError", "ValueError")

print(f"\n{ok} pasan, {fallos} fallan")
sys.exit(1 if fallos else 0)
