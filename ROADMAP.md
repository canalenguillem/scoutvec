# scoutvec — Roadmap

Vector-based player similarity search for football scouting.
Data: StatsBomb open data, La Liga 2015/16 (380 matches, full season).

## Phase 1 — Data foundation
- [x] Local StatsBomb loader (sparse clone, no HTTP rate limits)
- [x] Event flattening → `data/events.parquet` (1.29M rows)
- [x] Player-season aggregation → `players.parquet` (392 players, 600+ min)
- [x] Sanity check: Neymar/Messi top dribble_p90

## Phase 2 — Style vectors
- [ ] Positional grouping (collapse 20+ StatsBomb positions into ~6 roles)
- [ ] Percentile ranking within role (not raw p90 — a CB and a winger aren't comparable)
- [ ] Fixed-order feature vector per player
- [ ] Sanity check: cosine similarity Messi↔Neymar should be high, Messi↔Piqué low

## Phase 3 — Similarity search
- [ ] Qdrant collection + upsert
- [ ] `find_similar(player_id, k)` with filters (age, minutes, position)
- [ ] Sanity check: query Iniesta → expect Isco, Thiago, Koke

## Phase 4 — Interface
- [ ] FastAPI: `/players`, `/similar/{id}`
- [ ] React + Vite: search box, results list, radar chart comparison
- [ ] Screenshot for README

## Phase 5 — Natural language layer
- [ ] LLM: query → structured filters + target profile
- [ ] "A left-back under 23 outside the top-5 leagues who plays like Alba"
- [ ] Return the structured query alongside the answer (explainability)

## Phase 6 — Evidence clips
- [ ] Map similarity drivers → specific match events → timestamps
- [ ] ffmpeg assembly: 40s clip justifying each recommendation
- [ ] This is the differentiator — nobody else in this space ships video

## Phase 7 — Ship
- [ ] English README with screenshots + architecture diagram
- [ ] Write-up: what the data taught me, what the model can't do
- [ ] Cross-league extension: Premier (2,27), Serie A (12,27), Ligue 1 (7,27)

## Known limitations
- Minutes approximated from first/last event → undercounts GKs, low-touch players
- No age/market value data in StatsBomb open data (would need external join)
- Event data only — no tracking, so no off-ball movement, no pitch control
- 2015/16 season: a portfolio piece, not a live scouting tool