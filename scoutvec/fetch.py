# scoutvec/fetch.py
import json
from pathlib import Path

DATA = Path.home() / "code" / "open-data" / "data"

def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def competitions():
    return _load(DATA / "competitions.json")

def matches(comp_id, season_id):
    return _load(DATA / "matches" / str(comp_id) / f"{season_id}.json")

def events(match_id):
    return _load(DATA / "events" / f"{match_id}.json")