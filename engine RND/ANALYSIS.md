# Engine v2: how it works, and what is wrong with it

This is the write-up behind the code in this folder. It walks the whole v2
pipeline end to end, then lists every problem found, with the evidence for
each and what (if anything) was done about it here.

The headline first, because it is easy to lose in a long list: **the model
architecture is fine.** Artist-first shortlisting with track-level re-ranking
is the right call on a 1.7%-dense interaction matrix, and the intuition behind
it — artist preferences are denser and more stable than track preferences — is
correct. Almost everything below is about the code and the process around that
model, not the model itself.

---

## 1. The workflow, as it actually runs

Two notebooks (`engine_new.ipynb`, `engine_newer.ipynb`, largely
copy-pasted from one another) carry the whole pipeline. Nine stages:

```
 raw CSVs (track_reactions, tracks, artists, artist_reactions, reaction_types)
   │
 1 │ column pruning              process_csv() drops unused columns
   │                             ── also drops reacted_at, sentiment
   │
 2 │ artist backfill             flagged tracks with no artists_id are matched
   │                             by exact name, then by fuzzy name (>=95, gap>=10)
   │
 3 │ artist dedup                names NFKD-normalised, diacritics and invisible
   │                             chars stripped, grouped, smallest id wins
   │                             ── 5,396 rows -> 5,368 canonical artists
   │
 4 │ metadata parse              Last.fm JSON -> genres + related_artists
   │                             ── 22,025 related entries -> 7,139 matched edges
   │
 5 │ genre cleaning              normalise, fuzzy-cluster at token_sort_ratio 90
   │                             ── 2,087 raw genres -> 2,009 canonical
   │
 6 │ genre matrix                binary artist x genre, padded to all artists,
   │                             genres with <5 artists dropped
   │                             ── (5,368 x 2,023) -> (5,368 x 373), 0.71% dense
   │
 7 │ user-artist matrix          positive reactions (score > 1.0) weighted by
   │                             reaction score, + artist reactions, + uploads
   │                             at weight 5.0 each; then synthetic related-artist
   │                             edges at weight 0.2
   │                             ── 59,959 real -> 145,685 augmented interactions
   │
 8 │ two models                  HybridArtistMF: weighted BPR + edge loss, 100ep
   │                             TrackMF:        plain BPR on user x track, 100ep
   │
 9 │ export                      12 files to model_params/, read by
   │                             recommender.py behind main.py's four endpoints
```

Serving (`engine_v2/recommender.py`) is the same shape on every request:

```
user_id ─> trained artist vector ─┐
reacted_artist_ids ─> centroid ───┼─> stage 1: score all 5,107 artists
reacted_track_ids ─> centroid ────┘            take top N
                                               │
                                    stage 2a: take each artist's top
                                              `tracks_per_artist` tracks
                                               │
                                    stage 2b: re-rank by track model,
                                              or by popularity if the user
                                              has no track vector
                                               │
                                              top K
```

That much is sound. Below is what breaks.

---

## 2. Findings

Severity is about impact on the product, not about how hard the fix is.
"Fixed here" means there is code in this folder and a test covering it.

| # | Finding | Severity | Fixed here |
|---|---|---|---|
| **S-1** | Stage 1 ranks artists with a scoring function the model was not trained on | High | Yes, opt-in |
| **S-2** | Candidate truncation happens before exclusion, starving heavy listeners | High | Yes |
| **S-3** | 2,410 tracks (16% of the catalogue) can never be recommended | High | Yes |
| **S-4** | No pool widening, despite the manual prescribing it | Medium | Yes |
| **S-5** | Candidates without a track embedding are silently dropped | Medium | Yes |
| **S-6** | No diversity control; one artist can own an entire response | Medium | Yes |
| **S-7** | A known user's live reactions are discarded | Medium | Yes |
| **S-8** | `/suggest` is fully deterministic | Low | Yes |
| **S-9** | Cold-start centroids are on a different scale to trained vectors | Low | Yes |
| **S-10** | Stage 2 is a Python loop of individual dot products | Low | Yes |
| **S-11** | The dislike nudge shrinks the whole profile vector | Low | Yes |
| **S-12** | Onboarding ranks artists by catalogue size and has no diversity constraint | Low | Yes |
| **E-1** | Popularity used in evaluation is computed over train **and** test | High | Protocol + code |
| **E-2** | The artist model is trained on the artists of the held-out tracks | High | Protocol only |
| **E-3** | Model selection (the 1×26×2 sweep) runs on the test set | High | Protocol only |
| **E-4** | Published metrics are mislabelled and misinterpreted | High | Protocol + code |
| **E-5** | The split can leave a user with no training interactions | Medium | Yes |
| **T-1** | Interaction weights are unbounded; uploads dominate | Medium | Documented |
| **T-2** | Synthetic edges are counted twice and inflate the data 2.4× | Medium | Documented |
| **T-3** | Negative sampling does not exclude a user's observed positives | Low | Documented |
| **T-4** | `user_bias` can never learn anything under a BPR objective | Low | Documented |
| **T-5** | Only the first artist of a multi-artist track is ever used | Low | Documented |
| **D-1** | `reacted_at` is dropped during cleaning, foreclosing temporal evaluation | Medium | Documented |
| **D-2** | Dislikes are discarded on an assumption that was never tested | Low | Documented |
| **O-1** | The shipped model files match no notebook run in the repo | High | Yes |
| **O-2** | Four sources disagree about the serving parameters | Medium | Yes |
| **O-3** | No tests, anywhere | Medium | Yes |
| **O-4** | Artifact load has no validation; mismatched exports serve wrong answers | Medium | Yes |
| **O-5** | A failed model load produces a process that 500s on every request | Medium | Yes |
| **O-6** | Malformed query parameters return 500 with a traceback | Low | Yes |
| **O-7** | `start.sh` runs `pip install` on every restart | Low | Yes |
| **O-8** | 29 MB of binaries in git, 18 MB of which the service never reads | Low | Partly |
| **O-9** | `README.md` documents a `.env.example` that `.gitignore` prevents existing | Trivial | Noted |

### The ones worth reading in full

#### S-1 — Serving optimises a different function than training

`HybridArtistMF` scores a pair as

```
score(u, a) = user_emb[u] · artist_emb[a] + user_bias[u] + artist_bias[a]
```

`recommender.py` ranks artists with `profile.artist_vec @ artist_emb.T` —
the dot product alone. The bias is missing not by choice but by accident:
it lives only inside `artist_model_state.pt`, and the export step never wrote
it to `.npy`, so the serving process had no way to reach it.

It is not a small term. Read out of the shipped state dict it has standard
deviation 0.30 and spans −0.80 to +1.42, against artist scores whose spread is
the same order of magnitude. Ranking 5,107 artists with and without it gives
materially different shortlists.

`tools/build_params.py` recovers it (without importing torch — see
`tools/torch_pickle.py`) and the bundle carries it, so `artist_bias_weight`
now has something to apply.

**It still defaults to 0.0**, and that is a deliberate, measured choice rather
than a shrug. The bias is essentially a learned popularity term, and switching
it on costs real diversity: catalogue coverage falls from 8.2% to 6.3% and the
exposure Gini rises from 0.41 to 0.51 in the simulation below. Turning it on
would make this engine *more* concentrated than the one it replaces, on the
strength of a correctness argument with no accuracy measurement behind it. The
capability is there; the evidence to use it is not yet. See §4.

#### S-2 — Truncate-then-exclude starves exactly the users who use the product most

```python
# engine_v2/recommender.py
for aidx in top_artist_idxs:
    for tid in self._artist_to_tracks.get(int(aidx), [])[:tracks_per_artist]:
        if tid not in exclude:
            candidates.add(tid)
```

The slice runs first. So an artist contributes candidates only from its top
`tracks_per_artist` (shipped value: 10) tracks — and once a user has heard
those ten, that artist contributes **nothing**, no matter how large its
catalogue. The biggest artist in the dataset has 129 tracks; 119 of them are
unreachable for anyone who has heard the top ten.

The manual's own pseudocode gets this right (`artist_tracks = [t for t in ...
if t not in seen_tracks]`, *then* sort and slice). The shipped code inverted
it. This is the mechanism behind the "exhaustion" the docs worry about at
length, and it hits engaged users first.

Fixed by moving the exclusion inside the loop, before the cap.

#### S-3 — A sixth of the catalogue is unreachable

While building its artist→tracks index, `recommender.py` skips any track not
present in `track_id_to_idx`:

```python
if aidx is None or tid not in self.track_id_to_idx:
    continue
```

`track_id_to_idx` is derived from the *positive-reaction* matrix, so it only
contains tracks somebody has already reacted positively to. Counting from the
shipped artifacts: the catalogue has 14,843 tracks, 12,433 of them have at
least one positive reaction, and **2,410 have none**. Those 2,410 are exactly
the tracks that most need surfacing, and the engine cannot return them —
not through the model, not through the fallback, not ever.

Add the 552 tracks whose artist is unknown to the model and the total
unreachable set is 2,819 tracks, 19% of the catalogue.

Fixed: tracks with no reactions are legitimate candidates, carrying popularity
0. Reachability goes from 12,024 tracks to 14,291. The remaining 552 are
genuinely unaddressable — nothing maps them to an artist — and stay reachable
only via the popularity fallback.

#### S-6 — One artist can own the whole response

From engine_v2's own notebook output, a real user's five consecutive picks:

```
Regime A: 1/23/Ens:
  1: Track 5688 by Eminem
  2: Track 2846 by Eminem
  3: Track 6001 by Eminem
  4: Track 9991 by Eminem
  5: Track 5899 by Eminem
```

Nothing in the pipeline prevents this. The final sort is by score, and if one
artist's tracks occupy the top of the pool, that is the answer.

Two mechanisms address it here. `max_tracks_per_artist_in_result` caps a single
response (relaxing rather than returning a short list if the cap cannot be
met), and `session_damping` handles the case the cap cannot see: `/suggest`
returns one track at a time, so a per-response cap over a list of length one
does nothing. The damping term uses the caller's `exclude_track_ids` as a
stateless proxy for "what this user has already been served" and penalises
artists already well represented in it by `damping · log1p(count)`.

#### E-1 to E-4 — The published numbers do not mean what they say

Four separate problems, compounding:

1. **Popularity leaks.** `track_pop = mat.sum(axis=0)` is computed on the full
   interaction matrix, then used to order candidates while evaluating a
   held-out split. Every "most popular unseen track" decision during
   evaluation was made with test data in hand.

2. **The artist model sees the test set.** The user-artist matrix is built from
   *all* track reactions; only the *track* interactions are then split 80/20.
   Since a track's signal is aggregated into its artist, stage 1 was trained on
   the artists of the very tracks stage 2 was later scored on surfacing.

3. **Selection on test.** The 15 × 13 × 2 sweep in `engine_newer.ipynb`
   evaluates every configuration on the test split and reports the best. There
   is no validation split.

4. **Mislabelling.** The sweep prints `Precision@10` while computing
   `hits / TOP_K_FINAL` with `TOP_K_FINAL = 1`. `Summary.txt` then reads a
   Recall@1 of 0.038 as *"the single recommended track is a real liked track
   about 7.6% of the time"* — which does not follow from a recall figure at
   all. (The sweep's own precision@1 for that configuration is 0.1457.)
   Separately, `Summary.md` claims "~11.1% Recall@10 and ~8.4% Precision@10"
   while the notebook it describes printed 0.1004 and 0.0751.

`evaluation.py` provides the pieces to do this properly — a user-stratified
split that guarantees every user keeps training data, popularity computed from
one side of a split only, and metrics that are individually unit-tested,
including the hit-rate/recall distinction that got collapsed above, plus
coverage and Gini so that "recommend the same popular head to everyone" stops
looking like a win. Items 2 and 3 are training-side and cannot be fixed from a
serving folder; §4 spells out what has to change in the notebook.

#### O-1 — The shipped model does not correspond to any run in the repo

`ensemble_config.json` records 1,310 artist-model users, 5,107 artists and
genre_dim 373. Every training run whose output survives in the notebooks
printed **1,285 users × 4,919 artists**, and `engine_new.ipynb` used genre_dim
361. The artifacts on the server therefore came from a run nobody can
reproduce: no seed in the config, no data snapshot, no training date, no
fingerprint.

The v3 bundle records format, source path, creation timestamp, counts and a
content fingerprint, and `GET /health` reports the fingerprint — so it is
always possible to tell, from outside a running process, which artifacts it
holds.

#### O-2 — Four sources, four different answers

| Source | top artists | tracks per artist |
|---|---:|---:|
| `Manual.txt` §4 | 5 | 1 |
| `Summary.txt` §7 | 5 | 1 |
| `Summary.md` §6 | 15 | 10 |
| `model_params/ensemble_config.json` (what actually ships) | 20 | 10 |

The value in force is the fourth, and it is the only one nobody wrote
prose about. It is also not in the sweep grid — the sweep tried odd numbers of
artists from 1 to 29, so 20 was never measured.

`config.py` is now the single source: dataclass defaults, overridden by the
bundle's `serving` block, overridden by `ENGINE_*` environment variables, with
the resolved values reported by `/health`.

### The training-side findings, briefly

These need the raw CSVs and a retraining run, so they are documented rather
than fixed:

- **T-1, unbounded weights.** `UPLOAD_WEIGHT = 5.0` is added per uploaded
  track, so a user who uploaded 200 tracks by one artist reaches weight 1000
  for that pair, against a typical reaction weight of 3–5. Those weights
  multiply the BPR loss directly (`(w * bpr).mean()`), so a handful of pairs
  dominate the gradient. `log1p` or a percentile clip would cost nothing.
- **T-2, double-counted edges.** Related-artist edges are injected both as
  synthetic interactions at weight 0.2 *and* as an explicit edge loss. The
  injection takes the training set from 59,959 to 145,685 rows — 59% of every
  epoch is synthetic. Pick one mechanism, and measure with it off.
- **T-3, false negatives.** `neg = random.randint(0, n_items - 1)` only checks
  `neg != pos`. With ~113 positive artists per user, roughly 2% of sampled
  negatives are actually positives.
- **T-4, dead parameter.** `user_bias` appears in both the positive and the
  negative score, so it cancels in the BPR difference and never receives a
  gradient. Read out of the shipped state dict it is still exactly zero after
  100 epochs. Harmless, but it means nobody checked.
- **T-5, lost collaborators.** `to_canonical_artist` takes
  `str(artists_id).split(',')[0]` — the first artist only. Featured artists
  never enter the user-artist matrix.
- **D-1, no timestamps.** Cleaning drops `reacted_at`. A recommender evaluated
  on a random split rather than a temporal one measures a task nobody performs
  (predicting the past from the future), and recency weighting becomes
  impossible. Keeping one column would restore both.
- **D-2, untested assumption.** `Summary.md` asserts that dislikes are
  "socially driven" and can be ignored, and no experiment in either notebook
  tests it. It may well be true; it is presented as a finding, not a guess.

Two code-quality notes on the notebooks, since they cost real time: several
loops use `artist_enc.transform([x])[0]` and `if artist_id in
artist_enc.classes_` per item, which is a sort and a linear scan over 5,107
elements inside a 14,843-iteration loop; and `add_related_artist_edges` tests
`mat[u, r] == 0` element-wise on a CSR matrix, the slowest way to ask that
question. Both become dictionary lookups.

---

## 3. What was measured

`tools/benchmark.py` runs both serving algorithms over the same artifacts.
`V2Baseline` in that file is a faithful reimplementation of engine_v2's
`recommend_from_profile` — same truncate-then-exclude order, same dropping of
candidates without embeddings, no widening, no bias, no diversity — so this is
a comparison against what v2 does, not a straw man.

300 users, 20 consecutive one-track requests each, exclusions accumulating as
the session goes, both engines driven through the code path their own
`/suggest` endpoint uses:

| | engine_v2 | engine RND |
|---|---:|---:|
| Distinct artists in a top-10 response | 6.95 | **7.74** |
| Distinct artists over a 20-track session | 11.25 | **14.48** |
| Requests falling through to global popularity | 0.07% | **0.00%** |
| Catalogue coverage across all sessions | 12.86% | **14.07%** |
| Exposure Gini (lower is less concentrated) | 0.545 | **0.523** |
| Tracks the algorithm can *ever* return | 12,024 | **14,291** |
| Latency p50 / p95 | 0.27 / 0.43 ms | 0.40 / 0.58 ms |

Reproduce with `python tools/benchmark.py --users 300 --session-length 20`.

No accuracy numbers appear in that table, deliberately. Producing a
trustworthy one needs the interaction CSVs and a retrain under the protocol in
§4; quoting engine_v2's published figures for comparison would be quoting
numbers this document has just finished explaining are unsound.

What the table does measure is precisely the set of failures found in §2, and
the engine is better on every axis except a 0.13 ms latency increase.

Two other measurements worth recording:

- **Bundle size.** 29 MB of `model_params/` becomes an 11.1 MB bundle, because
  the three `.pt` files (18 MB) are build-time inputs, not serving inputs.
- **Serving dependencies.** scikit-learn leaves the venv entirely; the serving
  process no longer unpickles any file.

---

## 4. What is still open

**The accuracy question.** Nothing here establishes that this engine
recommends *better* tracks, only that it recommends more varied ones from more
of the catalogue and never runs dry. Settling it requires a retrain under a
protocol that fixes E-1 through E-3:

1. Split the track interactions per user first (`user_stratified_split`).
2. Build the user-artist matrix from the **training** interactions only, so the
   artist model cannot see the held-out tracks' artists.
3. Compute `track_pop` from the training interactions only
   (`popularity_from(split.train)`).
4. Carve a validation split out of train and select hyperparameters and serving
   parameters on that, never on test.
5. Report recall@k, precision@k, hit-rate@k, nDCG@k, coverage and Gini
   together, with `k` in the label (`evaluate_rankings` does this).
6. Re-run with `artist_bias_weight` at 0.0 and 1.0 and let the result decide
   the default.

Steps 1, 3 and 5 have tested implementations in `evaluation.py`. Steps 2 and 4
are notebook changes.

**A temporal split** would be better still, and is blocked on D-1: restore
`reacted_at` in the cleaning stage and the more honest evaluation becomes
available.

**Item cold start.** The 2,410 zero-reaction tracks are now reachable, but they
are ranked by an embedding trained on no data for them. The genre matrix
already exists and already helps cold-start *artists*; the same idea applied to
tracks — a content-based prior for items with no interactions — is the obvious
next piece of modelling work, and it is the one the product actually needs,
since a music-discovery bot whose job is surfacing unheard songs currently has
nothing to say about the 16% of the catalogue nobody has reacted to yet.

**The 552 unattributed tracks** need a data fix, not a serving fix: the artist
backfill stage (pipeline step 2) succeeded on 176 of 375 flagged tracks and
fuzzy matching recovered 4 more. The rest are still unattributed and invisible
to a pipeline that routes everything through artists.
