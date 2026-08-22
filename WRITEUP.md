# What the data taught me

Notes from building scoutvec — a similarity search over 1,419 footballers built
from event data alone. Not a tutorial. These are the things that were not
obvious beforehand, most of which cost real time to find out.

---

## The expensive lesson: percentiles must be global

The vector is 17 percentile ranks. The first version ranked each player
*within their own role* — centre-backs against centre-backs, wingers against
wingers — because that is how every scouting radar you have ever seen works.

It destroys the space.

Ranking inside a group flattens every group to the same uniform distribution.
A centre-back at the 90th percentile for passing and a winger at the 90th
percentile for passing end up with the same number, even though the winger
plays half as many passes. The vector stops encoding *what kind of player this
is* and encodes only *how good they are at their own job*. Piqué came out
adjacent to a winger.

With a global rank the positional structure appears on its own. Nobody tells
the model that Piqué is a centre-back, and his eight nearest neighbours are
eight centre-backs. Measured across all 1,419 players, neighbours share the
query player's role 76.8% of the time against a 17.2% chance baseline.

**The diagnostic that caught it** is now an assertion in the pipeline: with a
global average rank, exactly one player can hold percentile 1.0 in any metric.
It is arithmetic, not a heuristic. When six players held it — one per role —
the ranking had silently become per-group. The assertion fails loudly, and I
verified it fails by reintroducing the bug on purpose. An assertion you have
never seen fail is a decoration.

---

## Volume measures the team, not only the player

Barcelona had 67% of the ball; Carpi had 38%. A Barcelona player touches it
1.74 times as often, so every per-90 count is partly a measurement of his
employer. This is why the first version put Piqué next to Mathieu, his own
centre-back partner, and Busquets next to Gabi and Tiago.

Two attempts at a fix, one of which was wrong in an interesting way.

**Attempt one: replace counts with ratios.** A completion percentage cannot
scale with possession, so ratios should be immune. They are not. Measured as
the share of variance in each metric explained by which club you play for:

```
carry_p90          34%   <- volume, as expected
ball_receipt_p90   28%
pass_p90           24%
pass_completion    21%   <- a ratio, and just as contaminated
pass_comp_pressure 19%
...
touch_final_third 3.2%   <- clean
shot_p90          3.6%
aerial_win        3.9%
```

Ratios split in two. *Completion* ratios inherit team style — in a possession
side everybody completes more passes, because the passes available to them are
easier. *Shape* ratios — where you touch the ball, how often you shoot, whether
you win headers — are clean. The hypothesis was half right, which is worse than
being wrong, because half-right survives a casual check.

**Attempt two: divide by possession.** The obvious correction, and it makes
things worse. The relation between a metric and possession is affine,
`a + b·pos`, so dividing gives `a/pos + b`, which *decreases* steeply in
possession and injects a fresh possession signal of the opposite sign.
Subtracting the fitted line removes the linear component and nothing else:

```
no correction                  0.695
divide by possession           0.572
residualise all 17 features    0.450   <- adopted
chance baseline                0.000
```

(Correlation between a player's team possession and the mean possession of his
eight nearest neighbours.)

It is a partial fix and the README says so. What remains is *tactical* style,
which possession does not capture — a side that defends deep makes all its
defenders resemble each other regardless of how much they have the ball.

The payoff is visible: Mathieu dropped out of Piqué's top eight entirely, and
the players nearest Messi became Insigne, Ben Arfa and Papu Gómez. "Who plays
like this at a club that does not have 67% of the ball" is a scouting
question. "Who else plays for Barcelona" is not.

---

## Measure the defect, not something correlated with it

I tracked the team-context leak as *the share of top-8 neighbours who are club
teammates*: 3.0% against a 1.3% baseline. Barely more than twice chance. It
looked like a minor blemish.

The possession correlation on the same vector space was 0.695 against a 0.000
baseline. The defect was enormous; the metric I had chosen simply could not see
it. Teammates are a tiny fraction of any neighbour list, so the statistic has
almost no room to move, and I nearly concluded there was nothing to fix.

Pick the diagnostic that measures the thing itself.

---

## A join does not preserve row order

Mid-investigation I produced a confident, completely wrong reading — a
possession correlation of −0.08, i.e. "the defect does not exist" — and told
the user so. The cause: I extracted an array from one dataframe and applied it
to a dataframe built from a *different* join. Polars does not guarantee row
order across joins, so the array was silently misaligned with the rows it was
supposed to describe.

Nothing errored. Nothing looked wrong. The number was simply meaningless.

Any cross-frame numpy comparison now sorts deterministically and asserts
alignment before computing anything. The check costs one line and would have
saved a wrong conclusion delivered with confidence.

---

## StatsBomb encodes aerial duels asymmetrically

A duel *lost* is a `Duel` event with `duel.type == "Aerial Lost"`. A duel *won*
is not a Duel event at all — it is an `aerial_won` flag inside whichever event
resolved it: a pass, a clearance, a shot, a miscontrol.

Count only `Duel` events and you have every header a player lost and none of
the ones he won. Your aerial specialist looks like the worst header in the
league.

The validation that the reading was right: aerials won and Aerial Lost come out
at exactly 14,879 each in Serie A, as they must, since every header has one
winner and one loser. When a dataset offers you a check that has to balance,
take it.

A related trap: **a completed pass has no outcome.** StatsBomb records
`pass.outcome` only when the pass failed, so the column looks 92% empty and
completion rate is `outcome.is_null() / total`. Same for `pass.type`: null
means open play, and corners, throw-ins and goal kicks all carry a type.
Forget to exclude them and your corner taker is scored as a bad passer.

---

## Never let a model emit an answer and its explanation separately

The natural-language layer asks a model to turn "un central que saque el balón
jugado y gane de cabeza" into a query. The first version asked for a full
17-dimension profile plus a sentence describing it.

It returned a profile that moved only `aerial_win`, and a sentence claiming it
had also moved `pass_p90` and `prog_pass_p90`.

Nothing was broken. The model produced two artefacts that were free to
disagree, and the one shown to the user was the wrong one. The fix is not a
better prompt — it is structural. The model now emits *only* a list of
adjustments, each carrying the words from the request that justify it, and the
profile is derived from that list. Prose and profile cannot diverge because
there is one source of truth. A test asserts the derived profile equals the
adjustments.

The general shape: have the model produce the structured thing, derive the
human-readable thing from it, and never ask for both in one breath.

Related, and the reason the layer is defensible at all: **the model never
answers the question.** It translates the request into a structured query, and
the same deterministic vector search that powers every other endpoint executes
it. The structured query is returned with the results, so a wrong answer can be
traced to the dimension that was misread rather than shrugged at.

And the sanitising lives in code, not in the prompt — unknown metrics,
duplicate adjustments, out-of-range values, invalid roles and absurd result
counts are dropped server-side. A prompt is not a contract.

---

## Things that were true but not interesting

Worth recording so nobody re-derives them.

**Cosine works fine on all-positive vectors.** An early hypothesis said
percentile vectors, all in [0,1], would collapse cosine similarity toward 1 and
lose resolution. Minimum pairwise similarity is 0.116, mean 0.753. Measure
before rewriting your distance metric.

**Similarities are not comparable across dataset sizes.** The mean top-8
similarity in the 1,419-player space is 0.971, noticeably tighter than in the
single-league space it grew out of: more players means a denser neighbourhood
and higher raw numbers, with no improvement in quality. Compare ranks across
dataset sizes, never raw magnitudes.

**Memory, not disk, is the ingest constraint.** Four leagues are 59 MiB of
parquet but 5.3M rows accumulated as Python dicts before the DataFrame exists.
Ingesting one league at a time and flushing to a DataFrame every 50 matches
took peak RSS from 2.4 GB down to 1.2 GB *while the schema grew from 12 to 20
columns*.

**Delete the output at the start of the job, not before the write.** Putting
the delete immediately before `write_parquet` means a failed run leaves the
previous file sitting there looking freshly generated — precisely the stale
state the rule exists to prevent. And validate arguments *before* deleting
anything: an early version of the ingest deleted `events.parquet` and then
rejected an unknown league name, destroying the output on a typo.

---

## What the model cannot do

Stated plainly, because a portfolio piece that oversells is worse than one that
admits its edges.

- **Team context still leaks.** 0.450 possession correlation against a 0.000
  baseline, after the correction. Tactical style is not captured by possession.
- **No age, no market value.** StatsBomb open data has neither. "Find a young
  replacement for X" is unanswerable here; only "find a similar profile" is.
- **Minutes are approximated** from each player's first and last event in a
  match. This undercounts goalkeepers and dominant-team centre-backs. Fine for
  a 600-minute cut, not for anything finer. The proper fix is joining the
  lineups files.
- **Event data only.** No tracking, so no off-ball movement and no pitch
  control. A player's value without the ball is largely invisible.
- **Seventeen dimensions is thin.** Nothing about *who* the pass went to, no
  defensive positioning, no runs. The progressive-pass threshold — 10 yards
  closer to goal — is a reasonable convention, not a standard.
- **One season, 2015/16.** The architecture is season-agnostic; the source is
  two constants. This is a portfolio piece, not a live scouting tool.
- **Goalkeepers are excluded.** Their event profile is not comparable and would
  distort the percentile distribution.

---

## What I would do next

Normalising against team *identity* rather than possession would remove the
remaining 0.450 by construction — and would also delete real signal, since some
of what a player does is genuinely shaped by the side he plays in. I do not
think it is worth it, but it is the obvious next lever.

More interesting: the vector describes *what* a player does and says nothing
about *where* on the pitch, beyond a single final-third share. Zone-of-touch
distributions would probably do more for the space than another six volume
metrics.
