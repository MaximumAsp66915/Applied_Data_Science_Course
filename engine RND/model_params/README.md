# `model_params/` — the serving bundle

This directory is intentionally empty in git.

The engine needs about 11 MB of trained arrays to answer anything, and those
arrays already exist in the repository once, under `engine_v2/model_params/`
(29 MB there, because that folder also carries the three `.pt` files the
serving process never reads). Committing a second copy here would add ~11 MB
to every clone to store information the repository already has.

## Getting a bundle

```bash
python tools/build_params.py --source ../engine_v2/model_params --out model_params
```

That reads the v2 exports, recovers the artist bias from
`artist_model_state.pt` without torch, validates everything, and writes:

```
model_params/
  bundle.json              manifest: format, source, counts, fingerprint, serving defaults
  artist_user_emb.npy      (1310, 200)  float32
  artist_item_emb.npy      (5107, 200)  float32
  artist_bias.npy          (5107,)      float32   <- absent from the v2 exports
  track_user_emb.npy       (1239, 100)  float32
  track_item_emb.npy       (12433, 100) float32
  track_pop.npy            (12433,)     float32
  user_ids_artist.npy      (1310,)      int64
  user_ids_track.npy       (1239,)      int64
  artist_ids.npy           (5107,)      int64
  track_ids_scored.npy     (12433,)     int64
  catalogue_track_ids.npy  (14843,)     int64
  catalogue_artist_ids.npy (14843,)     int64
```

No pickles: that is what removes scikit-learn from the serving venv.

## Running without building one

If this directory has no `bundle.json`, the engine falls back to reading
`../engine_v2/model_params/` directly, read-only. That works, and the test
suite covers it, but two things are worse:

- it needs `scikit-learn` installed to unpickle the `LabelEncoder` files, and
- the artist bias is unavailable, so `artist_bias_weight` has nothing to apply.

Both are fine for a quick look; neither is right for a deployment.

## After a retrain

Point `--source` at the new export folder and rebuild. `bundle.json` records
the source path, the creation timestamp and a content fingerprint, and
`GET /health` reports that fingerprint — so it is always possible to tell,
from outside the process, exactly which artifacts a running engine holds.
That was not possible with engine_v2.
