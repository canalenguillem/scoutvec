# scoutvec — Project Notes

Vector-based player similarity search for football scouting.
Built as a portfolio piece targeting the football data industry.

---

## 1. Status

**Phases 1, 2 and 2.5 complete.** Four-league pipeline, 17-dim vector space.

| Artefact | Content |
|---|---|
| `data/events.parquet` | 5,301,066 flattened events, 4 leagues, `league` column |
| `data/events_<liga>.parquet` | one per league; the concat source, kept to avoid re-ingesting |
| `players.parquet` | 1,533 players, 600+ minutes, 64 columns |
| `vectors.parquet` | 1,419 outfield players, 17-dim style vector, possession-adjusted |

Roles: CB 276, FB 301, DM 202, CM 198, W 251, FW 191.
Leagues: La Liga 363, Ligue 1 357, Serie A 359, Premier 340.

Phase 2.5 sanity check — cosine nearest neighbours, cross-league:

```
~ Messi (W)              ~ Busquets (DM)           ~ Piqué (CB)
  .984 Candreva (W ,SA)    .973 Dier       (DM,PL)   .991 Umtiti     (CB,L1)
  .968 Saponara (CM,SA)    .972 Iturraspe  (DM,LL)   .988 Albiol     (CB,SA)
  .961 Vela     (W ,LL)    .971 Lucas Leiva(DM,PL)   .985 Armand     (CB,L1)
  .961 Halilović(CM,LL)    .969 Schneiderlin(DM,PL)  .978 Víctor Ruíz(CB,LL)
  .961 Neymar   (W ,LL)    .968 Fuego      (DM,LL)   .977 Vertonghen (CB,PL)
  .957 Insigne  (W ,SA)    .967 De Roon    (DM,SA)   .976 Mascherano (CB,LL)
  .955 Ben Arfa (CM,L1)    .966 Kéita      (DM,SA)   .975 Stones     (CB,PL)
  .951 Papu Gómez(W ,SA)   .966 Romao      (DM,L1)   .974 Rekik      (CB,L1)
```

**Position is not in the vector.** Role coherence is emergent. Measured over
all 1,419 players:

| metric | value | chance baseline |
|---|---|---|
| top-8 neighbours sharing the query's role | 76.8% | 17.2% |
| top-8 neighbours who are club teammates | 2.5% | 1.3% |
| corr(query possession, neighbours' possession) | 0.450 | 0.000 |

The cross-league result is the one that reads as a tool rather than a demo:
Piqué's nearest neighbour is Umtiti, who signed for Barcelona that summer.
And once possession is adjusted for, the players nearest Messi are Insigne,
Ben Arfa and Papu Gómez — the question "who plays like this at a club that
does not have 67% of the ball" is exactly the scouting question.

---

## 2. Data source

StatsBomb open data, **local sparse clone** at `~/code/open-data`.

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/statsbomb/open-data.git
cd open-data && git sparse-checkout set data/matches data/events
```

`competitions.json` comes along automatically in cone mode. `data/three-sixty`
is excluded deliberately — it is most of the repo's weight.

**Primary dataset: `competition_id=11`, `season_id=27` → La Liga 2015/16.**
380 matches, 20 teams, full season.

Also full for 2015/16 and available for a cross-league extension:
Premier League `(2, 27)`, Serie A `(12, 27)`, Ligue 1 `(7, 27)`.

---

## 3. Decisions and gotchas

Things learned the hard way. Each of these cost real time.

**GitHub raw API returns 429.** `statsbombpy` fetches one HTTP request per
match; ~900 requests gets rate-limited. A local clone removes the network from
the pipeline entirely and cut ingestion to 14 seconds.

**This machine has no AVX2.** Standard `polars` is compiled assuming it and
dies with SIGILL. Requires `polars-lts-cpu` (same import name, no code
changes). Likely cause: virtualised CPU masking host extensions — worth fixing
at the hypervisor level eventually, because numpy and torch will hit it too.

**`pl.DataFrame` needs an explicit schema.** Polars infers types from the
first ~100 rows; `xg` is null in all of them (early match events are never
shots), so the column is inferred as `Null` and the first real shot value
raises `ComputeError`. Explicit schema beats raising `infer_schema_length`
because it makes the pipeline deterministic.

**La Liga coverage is Messi-only** in every season except 2015/16. Seasons
list 18 "home teams" but only ~35 matches — those are Barcelona's fixtures,
not a full league. Always verify match count *and* team count before
committing to a dataset.

**Minutes are approximated** from a player's first and last event in each
match. This undercounts goalkeepers, dominant-team centre-backs, and
substitutes who don't touch the ball immediately. Good enough for a 600-minute
filter. The proper fix is joining `data/lineups/`, which is not in the sparse
checkout.

**Goalkeepers are excluded** from the vector space. Their event profile isn't
comparable to outfield players and would distort the percentile distribution.
392 players → 363 outfield.

**Percentiles must be global, not within-role.** This was the expensive
lesson of Phase 2. Ranking inside each role flattens every role to an
identical uniform distribution, so the vector loses all information about
what kind of player it describes — Piqué came out adjacent to a winger.
With global percentiles, positional coherence emerges from the event profile
alone. The diagnostic that caught it: exactly six players had
`pct_pass_p90 == 1.0`, one per role. With a global rank only one player in
the dataset can hold the maximum.

**Cosine works fine here.** An early hypothesis that all-positive vectors
would collapse cosine similarity was wrong: min pairwise similarity is 0.066,
mean 0.776. Measure before rewriting the distance metric. Note that with
1,419 players the neighbourhood is far denser than with 363 — top-8
similarities now sit at 0.97–0.99. Compare ranks across dataset sizes, never
raw magnitudes.

**Possession must be residualised, not divided out.** The obvious correction
for "Barcelona players touch the ball more" is to divide the volume metrics
by the team's possession share. It makes things worse. The relationship
between a metric and possession is affine, `a + b*pos`, so dividing gives
`a/pos + b`, which *decreases* steeply in possession and injects a new
possession signal of the opposite sign. Subtracting the fitted line removes
exactly the linear component and nothing else.

Measured, as correlation between a player's team possession and the mean
possession of his eight nearest neighbours:

```
no correction                    0.695
divide on-ball by possession     0.572
residualise all 17 features      0.450   <- adopted
chance baseline                  0.000
```

Role purity was unaffected (76.3% → 76.8%), so the correction is close to
free. It is a partial fix: 0.450 is still far from 0.000, because
residualising removes only the linear component and because team style has
dimensions that possession does not capture.

**Recent men's open data is a trap, the women's game is not.** Looking for a
more current dataset than 2015/16: the Bundesliga 2023/24 files in StatsBomb
open data have 34 matches and 18 team names, which reads like a thin league
until you count per team — Leverkusen appears in all 34 and everyone else in
2. It is one club's season. MLS 2023 is 6 matches. The only complete recent
multi-league season on offer is the women's: Liga F, FA WSL, Frauen Bundesliga
and Serie A Women, 2023/24, 634 matches, all with events.

This is the second time the same trap has appeared in this project. Count
matches *and* distinct teams *and* appearances per team before believing a
competition file.

**A second dataset is a schema change, not a config change.** Adding
`women-2023-24` meant every artefact needed a dataset in its name, MariaDB
needed a `dataset` column in its primary key, and Qdrant needed a collection
per space — because percentiles are computed within a population and two
populations cannot share an index without silently comparing incomparable
numbers. The migration drops and recreates `players`, which is derived, and
never touches `users`, which is not.

**Cosine to a mostly-neutral target ranks the wrong thing.** The
plain-language layer emits a few adjustments and leaves the other dimensions
at 0.5, and the first version fed that as a 17-dimension vector into a cosine
search. For "a centre-back good with her feet who keeps the ball under
pressure" it returned a defender in the 41st percentile for pass completion,
while the players who actually topped both requested dimensions did not appear
at all.

The arithmetic: fifteen dimensions at 0.5 and two at 0.7 give a squared norm
of 15(0.25) + 2(0.49) = 4.73, of which the two requested dimensions contribute
0.98 — about 21%. The other 79% of the similarity is measuring "be close to
average at everything else". The ranking answered a question nobody asked.

The fix is to rank only on the dimensions that were actually specified, using
the target to set a direction rather than a point: above 0.5 means higher is
better, below means lower is better, and the score is the mean strength in
that direction. Same query now returns players at 1.00 and 0.99. It also
works unchanged for "never defends", where the wanted direction is down.

Worth noting *why* the bug survived review: the results looked plausible. They
were centre-backs, they were plausible centre-backs, and the summary described
the right intention. Only checking the returned players' actual percentiles in
the requested dimensions exposed it. A user spotted it from a radar chart
before any test did.

**Say when a question cannot be answered.** Asked for a goalkeeper who plays
well with their feet, the system silently returned centre-backs — goalkeepers
are excluded from the vector space entirely. Inventing a plausible answer to
an unanswerable question is the worst failure mode a tool like this has,
because nothing about the output signals it. The translator now emits an
`unsupported` field for goalkeepers, age, market value, contracts and goals
scored, the API returns zero results with the reason, and the interface says
so instead of listing the nearest thing it could find.

**Do not let a model emit an answer and its explanation separately.** The
first version of the language layer asked for a full 17-dimension profile plus
a sentence describing it. For "un central que saque el balón jugado y gane de
cabeza" it returned a profile that moved only `aerial_win`, and a sentence
claiming it had moved `pass_p90` and `prog_pass_p90` as well. Nothing was
broken — the model simply produced two artefacts that were free to disagree,
and the one shown to the user was the wrong one.

The fix is structural, not a better prompt: the model now emits only a list of
adjustments, each with the words from the request that justify it, and the
profile is *derived* from that list. Prose and profile cannot diverge because
there is only one source of truth. A test asserts the derived profile equals
the adjustments.

The same shape applies to any LLM feature: have the model produce the
structured thing, derive the human-readable thing from it, and never ask for
both in one breath.

**A 17-axis radar needs its labels measured, not eyeballed.** This machine has
no browser Playwright can launch — the cached Chromium is missing 17 shared
libraries — so "render it and look at it" was not available. The substitute:
build the React component through Vite in SSR mode, render it to static SVG
against real API data, and assert on the geometry — that nothing exceeds the
viewBox, that no two axis labels overlap, that no `<text>` carries a series
colour. It found a real collision (`Clearances` x `Prog. pass`, the two
bottom axes, both centre-anchored and too wide) that shortening the labels
fixed. `web/radar-check.mjs`. Worth keeping even once a browser works: it is
faster than a screenshot and it fails loudly in CI.

**Two measurement traps cost real time here.** First, `pl.DataFrame.join`
does not preserve row order, so an array extracted from one join and applied
to a frame built from a different join is silently misaligned — this produced
a confident, completely wrong reading (possession correlation of -0.08,
i.e. "the defect does not exist") before an explicit alignment assertion
caught it. Sort deterministically and assert alignment before trusting any
cross-frame numpy comparison. Second, the teammate-share metric badly
understated the problem: 3.0% against a 1.3% baseline looks minor, while the
possession correlation on the same space was 0.695. Pick the diagnostic that
measures the defect directly, not a proxy that correlates with it.

**Ratios did not fix the team-context leak.** The hypothesis was that a ratio
cannot measure how much your team has the ball, so replacing counts with
ratios would decontaminate the vector. Measured: role purity @8 improved a
lot (67.4% → 76.3%), but the share of top-8 neighbours who are the query
player's own club teammates went *up*, 2.3% → 3.0% (1.3% chance baseline).

The diagnostic that explains it — variance in each metric explained by which
team you play for (eta²):

```
carry_p90          34%   <- volume: measures team possession
ball_receipt_p90   28%
pass_p90           24%
pass_completion    21%   <- ratio, but still team style
pass_comp_pressure 19%
...
touch_final_third 3.2%   <- clean: measures the player
shot_p90          3.6%
clearance_p90     3.6%
aerial_win        3.9%
pass_forward_share 5.3%
```

So ratios split in two. *Completion* ratios inherit team style — in a
possession side everybody completes more passes. *Shape* ratios — where you
touch the ball, how often you shoot, whether you win headers — are clean.
The real fix is normalising the volume metrics by team possession, not
swapping counts for ratios. Stated openly rather than quietly dropped.

**StatsBomb encodes aerial duels asymmetrically.** A duel *lost* is a `Duel`
event with `duel.type == "Aerial Lost"`. A duel *won* is not a Duel event at
all: it is an `aerial_won` flag inside whichever event resolved it — a pass,
a clearance, a shot, a miscontrol. Counting only Duel events gives you every
header a player lost and none he won. Validation that the reading is right:
aerials won and Aerial Lost come out at exactly 14,879 each in Serie A, as
they must, since every header has one winner and one loser.

**A completed pass has no outcome.** StatsBomb only records `pass.outcome`
when the pass was *not* successful, so completion rate is
`outcome.is_null() / total`, and the raw column looks 92% empty. The same
applies to `pass.type`: null means open play, and corners, throw-ins and goal
kicks all carry a type. Excluding them matters — a corner taker would
otherwise be scored as a bad passer.

**Ingest memory, not disk, is the constraint.** Four leagues are 58 MiB of
parquet but 5.3M rows accumulated as Python dicts before the DataFrame is
built. On an 11 GB machine with ~5 GB free that is where the pipeline dies.
Two fixes, both cheap: ingest one league at a time to its own parquet and
concatenate with `sink_parquet`, and flush rows to a DataFrame every 50
matches. Peak RSS went *down* from 2.4 GB to 1.2 GB while the schema grew
from 12 to 20 columns.

**Delete the output before the work, not before the write.** Putting
`os.remove(SALIDA)` immediately before `write_parquet` means a run that
fails leaves the previous file sitting there looking freshly generated —
exactly the stale-state trap this rule exists to prevent. Delete at function
entry. Related: validate arguments *before* deleting anything. An early
version of `ingest.run()` deleted `events.parquet` and then rejected an
unknown league name, destroying the output on a typo.

**Notebook state cost five debugging rounds.** Stale `V` in memory and a
stale `vectors.parquet` on disk produced byte-identical output across
supposedly different runs. Fix: run pipeline stages as modules from the
terminal (`python -m scoutvec.vectors`), delete the output file before
regenerating so a failed run cannot silently leave old data in place, and
keep an assertion that fails loudly — e.g. "only one player may have
percentile 1.0".

---

## 4. Roadmap

```
Phase 1 — Data foundation                                    [DONE]
  [x] Local StatsBomb loader
  [x] Event flattening → events.parquet
  [x] Player aggregation → players.parquet
  [x] Sanity check

Phase 2 — Style vectors                                      [DONE]
  [x] Collapse ~24 StatsBomb positions into 6 roles (roles.py)
  [x] Percentile ranking — GLOBAL, not within role
  [x] Fixed-order feature vector → vectors.parquet
  [x] Cosine sanity check passed, role coherence emergent

Phase 2.5 — Widen the dataset                                [DONE]
  [x] Parameterised COMP/SEASON → LIGAS dict in ingest.py
  [x] Pipeline over all four 2015/16 leagues → 1,419 outfield players
  [x] Cross-league search working

Phase 2.6 — Enrich the vector                                [DONE]
  [x] Capture end_location, length, under_pressure, aerial_won in ingest
  [x] 9 volume counts → 11 volumes + 6 ratios (17 dims)
  [x] Role purity @8 up from 67.4% to 76.3%
  [x] Residualise every feature against team possession — see §3
  [x] Possession clustering 0.695 → 0.450, teammates 3.0% → 2.5%
  [ ] Still 0.450 against a 0.000 baseline. Partly fixed, not solved.

Phase 3 — Similarity search                                  [DONE]
  [x] Target-vector search (hand-built profile, no reference player) —
      similarity.target() / perfil(), the Phase 5 mechanism by hand
  [x] find_similar with role + league filters
  [x] Qdrant collection + upsert, payload-indexed on role/league/team
  [x] Verified identical to the numpy reference on 62 sampled players

Phase 4 — Interface                                          [DONE]
  [x] FastAPI: /health, /meta, /players, /players/{id}, /similar/{id},
      POST /similar/target, /compare
  [x] React + Vite + TypeScript, 17-axis radar comparison up to 4 players
  [x] Table view, legend, light/dark, validated categorical palette
  [x] Docker Compose: frontend, backend, mariadb, qdrant, seed —
      one published port, nginx proxying /api

Phase 4.5 — Multi-dataset + auth                              [DONE]
  [x] datasets.py: un dataset = N ligas de una temporada, su propio espacio
  [x] Todo el pipeline acepta -d/--dataset; artefactos con sufijo
  [x] women-2023-24 construido: 740 jugadoras, 2.2M eventos, 4 ligas
  [x] Una coleccion Qdrant y una columna dataset por espacio
  [x] Login con scrypt, sesiones en MariaDB, cambio obligatorio de clave
  [x] 25 tests de autenticacion

Phase 5 — Natural language layer                             [DONE]
  [x] OpenAI structured outputs: query → adjustments + role/league/k
  [x] Profile derived from adjustments, so prose cannot contradict it
  [x] Structured query returned with the results (explainability)
  [x] 14 offline tests that need no API key and cost nothing
  [x] Plain-language box in the UI

Phase 6 — Visual evidence
  [ ] Decompose a similarity into per-dimension contributions (already works:
      normalised vectors make cosine a sum of 17 terms, so the share each
      dimension contributes is exact, not attributed)
  [ ] Pull the events behind the top contributors — Piqué's 448 progressive
      passes are in events.parquet with match, minute and both endpoints
  [ ] Draw them on a pitch: two players' pass maps side by side, touch zones,
      aerial duel locations
  [ ] Answers "show me why these two are alike" with a picture instead of a
      number, using only data already on disk

  Video was the original plan and is not buildable. Written out rather than
  deleted, because the reasoning is the useful part:

  - StatsBomb open data ships no video, and there is no legal source of full
    match footage for these leagues and seasons. Broadcast rights, not a
    technical obstacle. Recording from a piracy aggregator would put a
    compliance problem in a public repo aimed at an industry whose employers
    license this footage.
  - Even with video, `minute` is match clock, not playback time. Cutting an
    accurate clip needs a per-half kickoff offset that open data does not
    provide.
  - The legitimate route exists: SoccerNet distributes several hundred full
    broadcast matches under a research agreement, with annotations already in
    video time, which solves the sync problem too. If that access ever
    arrives, steps 1 and 2 above are unchanged and only the last one differs.

Phase 7 — Ship                                               [DONE]
  [x] English README — result first, then method, then limitations
  [x] Screenshots — taken by hand from the deployed site (this machine has no
      browser Playwright can launch), cropped into docs/
  [x] Architecture diagram (mermaid, renders on GitHub)
  [x] WRITEUP.md — what the data taught me, what the model can't do
```

---

### 4.1 Running it

```bash
uvicorn scoutvec.api:app --port 8000     # API, carga vectors.parquet en RAM
cd web && npm install && npm run dev     # frontend en :5180, proxy /api -> :8000
```

Vite uses `strictPort: true` on 5180 deliberately: with the default it silently
drifts to the next free port when 5173 is taken, and you end up reading another
project's app while believing it is yours. That happened.

No database. `vectors.parquet` is 1,419 x 17 floats loaded once at import;
a query is one matrix-vector product. Qdrant is still worth adding in Phase 3,
but for vector-DB fluency and an upgrade path, not for speed — and the README
should say exactly that rather than pretend it is a performance decision.

### 4.2 On adding MariaDB and Qdrant

This contradicts §5, which rejects exactly this. Recorded plainly: it was an
explicit decision to build the multi-service version, taken with the trade-off
stated. What keeps it from being purely decorative:

- **MariaDB has a real job.** Listings, substring search, ordering by minutes
  and the 17 percentiles as queryable columns — the things a vector index is
  bad at. Qdrant holds vectors and payload filters only, and neighbour results
  are hydrated from MariaDB by id.
- **The numpy backend still works and is still tested.** `SCOUTVEC_BACKEND=numpy`
  bypasses both services entirely. Keeping it is what makes the honesty
  possible: the README can say numpy is faster at this size because the claim
  is checked, not asserted.
- **Parity is verified, not assumed.** 62 sampled players return byte-identical
  neighbour lists from Qdrant and from numpy. Without that check, a silent
  divergence in distance metric or normalisation would look like "the database
  version behaves a bit differently".

The cost is real and should be stated in interviews rather than hidden: four
services and a seed step to do what a 550 KB file in memory already did.


## 5. Scope discipline

Explicitly rejected: MongoDB, Redis. MariaDB and a multi-service compose were
rejected here and then built anyway on an explicit decision — see §4.2, which
records the trade-off rather than pretending the rule was never broken.

Also rejected: **a betting model inside this repo.** Explored with real data
before deciding. football-data.co.uk publishes results and opening/closing
odds for 20 divisions back to 1993/94, updated as matchdays are played, and it
is free and legitimate — but the closing line is calibrated to within a point
of observed frequency across the bulk of matches (Brier 0.572 against 0.630
for the base rate), and the house margin is 6.13%, so a model must be 5.8%
sharper than the market merely to break even. Worth doing as its own project
and a genuinely strong portfolio piece for a quant shop; worth keeping out of
a scouting tool, which is a different question over different data.

392 rows fit in a parquet file. Adding four datastores to a single-process
tool that reads a local file is résumé-driven architecture, and technical
reviewers in this industry read it as an inability to separate essential from
decorative. Docker enters at Phase 4 with exactly two services — API and
Qdrant — in a ~15-line compose file.

Known limitations to state openly in the README:

- Minutes approximated (see above)
- No age or market value in StatsBomb open data — needs an external join.
  Until then "find a *young* replacement for X" is not answerable, only
  "find a similar profile to X".
- Event data only: no tracking, so no off-ball movement, no pitch control
- 2015/16 season — a portfolio piece, not a live scouting tool. The
  architecture is season-agnostic; swapping the source is two constants.
  Demonstrating the same system across two leagues and two eras is stronger
  evidence of a tool than one recent league would be.
- **Team context still leaks into the vector**, though much less than before.
  Mathieu has dropped out of Piqué's top 8 entirely. After residualising
  against team possession the space still shows 0.450 correlation between a
  player's team possession and his neighbours' (0.000 would be none), and
  2.5% teammates in the top 8 against a 1.3% baseline. Swapping counts for
  ratios did not help; residualising did, partially. What remains is team
  *tactical* style, which possession does not capture — a side that defends
  deep makes all of its defenders look alike regardless of how much they
  have the ball.
- **Possession is a proxy, not a measurement.** It is the team's share of
  on-ball events in each match, weighted by the player's minutes — not
  timed possession. It validates to a mean of exactly 0.500 because the two
  teams' shares sum to 1, and the season extremes are the right clubs
  (Barcelona 0.67, PSG 0.66, Carpi 0.38), but it is still a count.
- **17 metrics is better than 9 but still event-count-shaped.** Missing:
  anything about *who* the pass went to, defensive positioning, and off-ball
  runs. Progressive passes here use a 10-yard-closer-to-goal threshold, a
  reasonable convention rather than a standard one.
- Minutes are still approximated, so ratios are safer than p90 volumes for
  any player near the 600-minute cut.

Listing what the model *cannot* do reads as maturity. Most portfolios in this
space oversell.


---

## 6. Next session

All four items from the previous list are done: `similarity.py` as a module,
`similar_role()`, target-vector search, and the four-league pipeline.

The pipeline is three commands, in order, each safe to re-run:

```bash
python -m scoutvec.ingest      # ~3 min, all four leagues
python -m scoutvec.features    # players.parquet
python -m scoutvec.vectors     # vectors.parquet + the 1.0 assertion
python -m scoutvec.similarity  # Messi / Busquets / Piqué
```

Candidates, in the order they probably deserve:

1. **Screenshots into the README.** Two images, five minutes, and they are the
   first thing a reader looks at. Needs a browser, so it is a manual step.
2. **Phase 3 — Qdrant.** Note honestly that 1,419 vectors × 17 dims is
   instant in numpy; Qdrant buys portfolio evidence of vector-DB fluency and
   an upgrade path, not speed. The API already isolates the query behind
   `similarity.vecinos()`, so swapping the backend touches one function.
3. Optional, only if the vector gets revisited: the residual 0.450 possession
   clustering would need a team-style control rather than a possession one.
   Residualising against team *identity* would remove it by construction but
   would also delete real signal. Not obviously worth it.

Working method: pipeline stages as modules run from the terminal. The
notebook is for looking at results, never for producing them.

Tooling note: this project is a good fit for Claude Code — it writes to disk,
runs the module, reads the real error and iterates, which removes the
copy-paste and stale-state friction entirely. Hand the agent `PROJECT.md` as
context plus one concrete phase at a time; never "build the whole stack".