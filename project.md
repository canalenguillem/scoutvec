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

Phase 5 — Natural language layer                             [DONE]
  [x] OpenAI structured outputs: query → adjustments + role/league/k
  [x] Profile derived from adjustments, so prose cannot contradict it
  [x] Structured query returned with the results (explainability)
  [x] 14 offline tests that need no API key and cost nothing
  [x] Plain-language box in the UI

Phase 6 — Evidence clips
  [ ] Similarity drivers → match events → timestamps → ffmpeg
  [ ] The differentiator: nobody in this space ships video

Phase 7 — Ship
  [x] English README — result first, then method, then limitations
  [x] Screenshots — taken by hand from the deployed site (this machine has no
      browser Playwright can launch), cropped into docs/
  [ ] Architecture diagram
  [ ] Write-up: what the data taught me, what the model can't do
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

Explicitly rejected: MariaDB, MongoDB, Redis, multi-service Docker Compose.

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

## 6. Career context

### 6.1 Constraint update

Earlier planning assumed alternating-week custody as a hard limit on
relocation. That assumption is out of date. Children are 22, 18, and turning
17; the two eldest are effectively independent.

This widens the option space considerably — relocation to another European
city is now genuinely on the table rather than theoretically. It does not make
the decision automatic. The youngest is 16 and currently in conflict with her
mother, which is exactly the age and situation where physical proximity to the
other parent can matter more, not less. That is a judgement call about the
next 18 months specifically, not a permanent constraint, and it belongs in the
decision — but it argues for *remote-first or short-haul* over *another
continent*, rather than against moving at all.

### 6.2 Where the money actually is

Ranked roughly by compensation, not by prestige. Verify all figures — these
are directional and the market moves.

**Tier 1 — Betting and trading.** Smartodds, Starlizard, Bet365, Flutter,
Sportradar's trading arm. These pay tech-market rates or above because they
are quant shops that happen to model football. Highest ceiling by a wide
margin. Mostly London-based, which means a UK Skilled Worker visa — real
friction for an EU passport post-Brexit, though these firms sponsor routinely.

**Tier 2 — Sports-tech vendors.** StatsBomb (Hudl), SkillCorner, Metrica
Sports, Second Spectrum, Stats Perform, Zelus. Product companies with real
engineering orgs, remote-friendly, and they hire *engineers* rather than
analysts. **This is the best fit for a 25-year backend profile.** Kognia
(Barcelona) and Driblab (Madrid) are the Spanish options — smaller, lower pay,
but no relocation.

**Tier 3 — Clubs.** Premier League clubs pay best (Liverpool, City, Brighton,
Brentford, Arsenal all have real data departments). Red Bull group, Ajax,
Benfica, Club Brugge also. But club salaries are generally *below* equivalent
tech roles, the teams are small, hiring is rare, and the work skews toward
serving coaching staff rather than building systems. Prestige is high;
compensation is not.

**Tier 4 — Spanish clubs.** Few positions, low pay, brutal competition.
Barcelona specifically has an obvious financial situation. Treat as a
long-shot narrative anchor for the project, not a plan.

### 6.3 Strategic read

The realistic path is **Tier 2, remote or short-haul**, not a club analyst
role. Club roles require full physical presence, matchday weekends and travel
— the worst possible fit — and pay less for it.

`scoutvec` sells to all four tiers, which is why the project should stay
club-agnostic. No crests, no club names in the repo. A project that reads as
"I want to work at one specific club" costs you with the other five employers.

Entry points worth tracking:

- **"More than a Hack"** — Barça Innovation Hub + Metrica Sports, run at
  Talent Arena during MWC Barcelona (March). Generative AI applied to real
  FC Barcelona tracking and event data. The 2026 edition was the closest
  thing to this exact profile written as an open call.
- **Sports Tomorrow Congress** — BIHUB's annual congress, also at MWC in
  March. Has historically run a research-paper competition.
- **PySport open source** — kloppy, mplsoccer, socceraction. A merged PR is
  worth more than fifty LinkedIn applications, because the maintainers and
  the industry are the same people.

### 6.4 On paid courses

Not worth it here. 25 years of engineering plus StatsBomb's own documentation
and Sumpter's *Soccermatics* covers the domain gap for free. What's missing
isn't knowledge of xG — it's a finished, visible project. Money and hours go
to Phase 2 through 7.

---

## 7. Next session

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