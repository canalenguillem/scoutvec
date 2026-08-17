## Data source
- Local clone: ~/code/open-data (sparse: data/matches, data/events)
- PRIMARY: competition_id=11, season_id=27 → La Liga 2015/16, 380 matches (full season)
- Also full 2015/16: Premier (2,27), Serie A (12,27), Ligue 1 (7,27)
  → cross-league similarity = future extension
- Warning: most other La Liga seasons are Messi-only coverage, not full seasons

## Session 1 — done
- 1,290,501 events → data/events.parquet
- 392 players (600+ min) → players.parquet
- Sanity check passed: Neymar/Messi top dribble_p90, Isco 5th

## Gotchas
- GitHub raw API → 429. Use local clone of statsbomb/open-data (sparse-checkout).
- This CPU has no AVX2 → requires `polars-lts-cpu`, not `polars`.
- pl.DataFrame needs explicit schema (xg is null in first ~100 rows → inferred as Null).
- La Liga coverage is Messi-only except season 27 (2015/16, full 380 matches).
- Minutes are approximated from first/last event. Undercounts GKs and low-touch players.