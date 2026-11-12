# SUT Music recommendation engine — v3

Standalone FastAPI microservice, same role and **same HTTP contract** as `engine_v1/` and
`engine_v2/` (`/health`, `/suggest`, `/recommend`, `/onboarding`; `/health` only gained
`model_version` and `trained_at`). `app/webapp/engine_client.py` keeps working untouched.
Binds to `127.0.0.1` only. The server runs exactly one engine at a time: whichever
`engine_v*` folder was pushed last is rsynced into its `engine/` by
`.github/workflows/deploy-engine.yml` (highest changed version wins).

Inference is numpy-only (no torch on the server). Training is a separate, repeatable script.

## How it recommends

Two stages (same shape as v2):

1. **Artist stage** — `HybridArtistMF`: user embedding · (artist id-embedding + projection of
   its Last.fm genres) + artist bias; weighted BPR loss plus a regulariser pulling
   Last.fm-related artists together. Picks the top 120 artists for the user.
2. **Track stage** — `TrackHybrid`: user embedding · (track id + **artist** + **uploader**
   embeddings). Ranks the top-30 *unseen* tracks of each candidate artist, blended with a
   small popularity prior (`pop_weight`).

Users the model never saw get a profile averaged from the artists/tracks they reacted to;
with no signal at all they get the most popular tracks.

## What changed vs v2

| | v2 | v3 |
|---|---|---|
| Training | notebook, cells run by hand | `train.py`, one command, ~2.5 min on a laptop CPU |
| `artist_reactions.csv` | counted on top of track reactions | they are 100 % bot-generated duplicates of track reactions (74,316 of 74,331 sit within 3 s of the same user's same-emoji track reaction); only used where no track reaction covers the (user, artist) |
| Multi-artist tracks | first artist only | every credited artist gets credit and can surface the track (2,891 tracks have 2+ artists) |
| Repeat / self reactions | a user's several emojis on one track counted separately; reacting to your own upload counted | one (user, track) pair counts once; self-reactions dropped (the upload is already a signal) |
| Track model | id embeddings only | id + artist + uploader embeddings; uploads count as positives; tracks nobody has liked yet are still in the model |
| Candidate cut | top-N per artist **before** removing seen tracks → heavy listeners ran out of candidates | top-N **unseen** per artist |
| Serving knobs | fixed 15–20 artists × 10 tracks | 120 × 30, artist bias and popularity prior, chosen on validation data |
| Duplicate artist ids from the app | silently ignored | mapped to the canonical artist (`artist_alias.pkl`) |

Tried and rejected on validation data: using dislikes as hard negatives for the track model
(0 % > 20 % > 50 %, so it is off — dislikes still never get recommended again if the app passes
them in `exclude_track_ids`), larger embeddings, longer training, stronger weight decay.
Removing the artist feature from the track model costs ~20 % ndcg; the uploader feature is neutral.

## Measured quality (be sceptical of all of it — the data is small)

Metrics are macro-averaged over users, top-10, tracks the user already reacted to / uploaded
excluded. Data: 90 k track reactions, ~1.3 k users, 15.9 k tracks.

**Random hold-out** (15 % of each user's likes hidden, 787 users): v3 ndcg@10 ≈ 0.097 vs 0.030 for
"most popular unseen" — about 3×, ~1 user in 3 gets a hit in their top 10.

**Out-of-time** (train on everything before Oct 12, test on the likes after it; 140 users, 1,077
target likes; Aug 8 cutoff gave the same picture). This split was NOT used for any tuning:

| engine | recall@10 | precision@10 | hit@10 | hit@1 | ndcg@10 |
|---|---|---|---|---|---|
| popularity | 0.020 | 0.015 | 0.136 | 0.007 | 0.022 |
| **v1** (what ran in production until v3) | 0.004 | 0.001 | 0.007 | 0.000 | 0.002 |
| v2 (never deployed) | 0.031 | 0.015 | 0.114 | 0.036 | 0.029 |
| **v3** | 0.019 | 0.016 | 0.143 | 0.021 | 0.025 |

Paired bootstrap over users, both out-of-time splits: **v3 is significantly better than v1** on every
metric (hit@10 +11 to +14 points, interval excludes 0); **v3 vs v2 and both vs popularity are not
distinguishable** (all intervals contain 0). Out-of-time likes skew toward already-popular tracks
(median popularity 9 vs 3 for the catalogue) and only ~20 users per split get any hit, so that test
cannot separate personalised models from popularity. Serving knobs (`n_artists`, `tracks_per_artist`,
`artist_bias_weight`, `pop_weight`) were picked by worst-case over the random split and the Aug 8
split; the Oct 12 split is the untouched check.

## Retraining

```bash
python -m venv .venv-train && source .venv-train/bin/activate
pip install -r requirements-train.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu     # CPU build is enough
python train.py --data-dir /path/to/csv_exports --split full           # writes model_params/
```

* The five CSVs (`track_reactions`, `artist_reactions`, `reaction_types`, `artists`, `tracks`)
  are exports of the Postgres tables and **must keep their header row** (read by column name).
* **Train with the pinned `numpy==1.26.4` / `scikit-learn==1.5.2`** (`requirements-train.txt`):
  `model_params/*.pkl` are pickled `LabelEncoder`s and the server's venv has exactly those pins.
* `--split temporal --set cutoff=YYYY-MM-DD` / `--split random` + `--tune-serving` reproduce the
  validation numbers above; `tools/compare_engines.py` scores v1/v2/v3 on the same out-of-time test.
* Hyper-parameters are overridable: `--set art_dim=200 trk_epochs=100 ...` (see `HParams`).

## Checking a running engine

```bash
python tools/smoke_test.py --base-url http://127.0.0.1:8100 --params-dir model_params
```

22 checks of the HTTP contract (shapes, exclusion honoured, every fallback, validation, latency).

## Rolling back

The deploy workflow ships the highest `engine_v*` folder **changed in the push**. To go back, push
a change that touches only the folder you want live (e.g. `engine_v2/` or `engine_v1/`).

## `model_params/`

`ensemble_config.json` (dims, serving knobs, hyper-parameters, train timestamp), `*_enc.pkl`
(id ↔ index), `artist_{user,artist}_embeddings.npy`, `artist_bias.npy`,
`track_{user,item}_embeddings.npy`, `track_pop.npy`, `track_to_artist.pkl`, `track_artists.pkl`,
`track_id_to_idx.pkl`, `artist_alias.pkl`. `artist_bias.npy`, `track_artists.pkl` and `artist_alias.pkl`
are v3 additions; v3's `recommender.py` treats them as optional, so it can still load a v2-style folder.
