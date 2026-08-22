# scoutvec

Find footballers who play like a given player, across four leagues, from event
data alone.

Ask it for players similar to Gerard Piqué and it returns Samuel Umtiti — who
signed for Barcelona that summer — followed by Raúl Albiol, Jan Vertonghen and
John Stones. **Position is never given to the model.** That the neighbours of a
centre-back are centre-backs is an emergent property of the event profile, and
it is the main evidence that the vector captures playing style rather than
activity volume.

```
~ Messi (W, Barcelona)       ~ Busquets (DM, Barcelona)     ~ Piqué (CB, Barcelona)
.984 Candreva (Lazio)        .973 Dier (Tottenham)          .991 Umtiti (Lyon)
.968 Saponara (Empoli)       .972 Iturraspe (Athletic)      .988 Albiol (Napoli)
.961 Vela (R. Sociedad)      .971 Lucas Leiva (Liverpool)   .985 Armand (Rennes)
.961 Halilović (Gijón)       .969 Schneiderlin (Man Utd)    .978 Víctor Ruíz (Villarreal)
.961 Neymar (Barcelona)      .968 Fuego (Valencia)          .977 Vertonghen (Tottenham)
.957 Insigne (Napoli)        .967 De Roon (Atalanta)        .975 Mascherano (Barcelona)
.955 Ben Arfa (Nice)         .966 Kéita (Roma)              .975 Stones (Everton)
.951 Papu Gómez (Atalanta)   .966 Romao (Marseille)         .974 Rekik (Marseille)
```

Messi's neighbours are worth a second look. They are not the other superstars —
they are Insigne, Ben Arfa and Papu Gómez. Because the vector is adjusted for
team possession, the question it answers is *"who plays like this at a club that
does not have 67% of the ball"*, which is the question a scout actually has.

<!-- Screenshots: open http://localhost:5180 and capture the app, then drop the
     files in docs/ and uncomment. Two are enough: the radar with 3-4 players
     selected, and the same comparison in table view.
![scoutvec comparing four players](docs/radar.png)
-->

## What it does

- **Similar players** — nearest neighbours by cosine, filterable by role and
  league. "Messi's profile, but in the Premier League" returns Payet, Bolasie
  and Tadić.
- **Target-profile search** — describe a profile by hand with no reference
  player (high shooting, high final-third touches, low interceptions) and get
  the players who match. This is the mechanism a natural-language layer would
  drive.
- **Side-by-side comparison** — up to four players on a 17-axis percentile
  radar, with a table view of the same numbers.

## The vector

1,419 outfield players with 600+ minutes, from 5.3M StatsBomb events across
**La Liga, Premier League, Serie A and Ligue 1, 2015/16**.

Each player is 17 dimensions — 11 per-90 volumes and 6 ratios:

| | |
|---|---|
| **Volumes** | passes, shots, dribbles, pressures, carries, ball receipts, duels, interceptions, clearances, progressive passes, progressive carries |
| **Ratios** | pass completion, pass completion under pressure, forward-pass share, long-pass share, share of touches in the final third, aerial duels won |

Three decisions do most of the work:

**Percentiles are global, never within-role.** Ranking inside each role
flattens every role to an identical uniform distribution, and the vector loses
all information about what kind of player it describes. The pipeline asserts
this: with a global rank at most one player can hold percentile 1.0 in any
metric, so more than one is a loud failure.

**Every feature is residualised against team possession.** A Barcelona player
sees the ball 1.74× as often as a Carpi player, and raw volumes measure that as
much as they measure the player. The correction is to subtract the fitted line,
not to divide — the relationship is affine, so dividing overshoots and injects a
possession signal of the opposite sign.

**Position is not an input.** It is used only as a query-time filter and as a
way to measure whether the space works.

## Does it work

Measured over all 1,419 players, on their eight nearest neighbours:

| | value | chance baseline |
|---|---|---|
| neighbours sharing the query's role | **76.8%** | 17.2% |
| neighbours who are club teammates | 2.5% | 1.3% |
| corr(query's team possession, neighbours') | 0.450 | 0.000 |

Role coherence at 4.5× chance, with position never given to the model, is the
result worth having. The other two rows are honest reporting of what is *not*
fixed — see limitations.

## What it cannot do

- **Team context still leaks.** 0.450 possession correlation against a 0.000
  baseline. Residualising helped (it was 0.695); it did not solve it. What
  remains is tactical style, which possession does not capture: a side that
  defends deep makes all its defenders look alike.
- **No age and no market value.** StatsBomb open data has neither, so *"find a
  young replacement for X"* is unanswerable. Only *"find a similar profile"* is.
- **Minutes are approximated** from each player's first and last event in a
  match. This undercounts goalkeepers and dominant-team centre-backs. Good
  enough for a 600-minute cut, not for anything finer.
- **Event data only.** No tracking, so no off-ball movement and no pitch
  control. A player's value without the ball is largely invisible here.
- **One season, 2015/16.** The architecture is season-agnostic — the source is
  two constants — but this is a portfolio piece, not a live scouting tool.
- **Goalkeepers are excluded.** Their event profile is not comparable and would
  distort the percentile distribution.

## Running it

Requires the [StatsBomb open data](https://github.com/statsbomb/open-data)
repository cloned locally:

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/statsbomb/open-data.git ~/code/open-data
cd ~/code/open-data && git sparse-checkout set data/matches data/events
```

Build the data (about four minutes end to end):

```bash
pip install -r requirements.txt
python -m scoutvec.ingest      # 5.3M events -> data/events.parquet
python -m scoutvec.features    # -> players.parquet
python -m scoutvec.vectors     # -> vectors.parquet, with the percentile assertion
python -m scoutvec.similarity  # nearest neighbours in the terminal
```

### With Docker

`vectors.parquet` is committed (550 KB), so the stack runs without downloading
StatsBomb or building anything:

```bash
python preflight.py            # checks the published port is free
docker compose up -d --build   # http://localhost:8090
```

Four services. **Only the frontend publishes a port**; the backend, MariaDB and
Qdrant talk over the compose network and cannot collide with anything else on
the machine.

```
frontend  nginx + built Vite app       :8090 -> 80   (the only published port)
backend   FastAPI / uvicorn            internal
mariadb   metadata, filters, listings  internal
qdrant    the 1,419 vectors            internal
seed      loads the parquet into both, then exits
```

nginx proxies `/api/` to the backend, which is what makes one published port
enough. `seed` runs once and the backend waits for it to exit successfully.

### Without Docker

```bash
uvicorn scoutvec.api:app --port 8000    # SCOUTVEC_BACKEND=numpy by default here
cd web && npm install && npm run dev     # http://localhost:5180
```

Set `SCOUTVEC_BACKEND=numpy` and the API skips both databases and reads
`vectors.parquet` into memory — that is the development path, and it needs no
services at all.

**On the databases, honestly:** 1,419 × 17 floats is a numpy matrix-vector
product, and numpy beats both stores at this size. MariaDB and Qdrant are here
as the shape the system would take two orders of magnitude further up —
MariaDB doing listings, substring search and filters, Qdrant doing filtered
approximate nearest neighbours. They are not a performance decision, and the
numpy backend is kept working precisely so the comparison stays honest. Both
paths are verified to return identical neighbours.

| endpoint | |
|---|---|
| `GET /meta` | features, roles, leagues, teams |
| `GET /players` | filter by name, league, role, team |
| `GET /players/{id}` | one player's 17-dimension profile |
| `GET /similar/{id}` | nearest neighbours, `?role=`, `?same_role=`, `?league=` |
| `POST /similar/target` | hand-built profile, no reference player |
| `GET /compare?ids=` | several profiles in one call |

Interactive API docs at `http://localhost:8000/docs`.

## Layout

```
compose.yaml      four services; only the frontend publishes a port
preflight.py      refuses to start if the published port is taken
Dockerfile        backend image
scoutvec/
  fetch.py        local StatsBomb reader
  ingest.py       events -> data/events.parquet, one league at a time
  features.py     per-player aggregation, ratios, possession share
  roles.py        ~24 StatsBomb positions -> 6 roles
  vectors.py      global percentiles, possession residualisation, the vector
  similarity.py   cosine search; also runs standalone as a CLI
  store.py        MariaDB schema + Qdrant collection + the seed
  api.py          FastAPI, with pluggable numpy / stores backends
web/              React + Vite + TypeScript; the radar is hand-written SVG,
                  no chart library. nginx serves it and proxies /api.
```

`project.md` holds the full engineering log — the decisions, the measurements,
and the mistakes that cost real time.

## Data

[StatsBomb open data](https://github.com/statsbomb/open-data), used under its
licence. This project is not affiliated with StatsBomb or with any club.
