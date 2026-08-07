"""Convert an ``engine_v2/model_params/`` folder into a v3 serving bundle.

    python tools/build_params.py --source ../engine_v2/model_params --out model_params

What the conversion buys, over pointing the engine straight at the v2 folder:

* **No pickles at serve time.** The four ``*_enc.pkl`` files exist only to
  carry ``LabelEncoder.classes_``, a plain integer array. Writing those arrays
  out as ``.npy`` removes scikit-learn from the serving venv entirely and
  stops the service from unpickling files on startup.
* **The artist bias comes along.** ``artist_bias`` is part of the artist
  model's scoring function but was never exported to ``.npy``, so engine_v2
  ranked artists with a function it had not trained. It is recovered here from
  ``artist_model_state.pt`` -- without importing torch, see ``torch_pickle``.
* **A manifest.** Format version, source, creation time, counts, a content
  fingerprint and the serving defaults, so a running process can say exactly
  which artifacts it holds.
* **Validation up front.** The consistency checks in ``artifacts.Params`` run
  at build time, so a bad export fails here rather than at 3 a.m. on the
  server.

The script never writes to ``--source``.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from artifacts import BUNDLE_FORMAT, V3_ARRAYS, Params, _fingerprint  # noqa: E402
from tools import torch_pickle  # noqa: E402


def _classes(path: Path) -> np.ndarray:
    """Pull ``.classes_`` out of a pickled LabelEncoder.

    Done with a stub class rather than a real scikit-learn import: the array
    is stored as a plain pickled ndarray inside the object's ``__dict__``, so
    nothing about scikit-learn is actually needed to read it, and requiring
    the exact version that wrote the file (they differ -- the training run
    used 1.6.1) just makes the build fragile.
    """

    class _Stub:
        pass

    class _Unpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module.startswith("sklearn"):
                return _Stub
            return super().find_class(module, name)

    with path.open("rb") as fh:
        obj = _Unpickler(fh).load()
    classes = getattr(obj, "classes_", None)
    if classes is None:
        raise SystemExit(f"{path.name}: no classes_ attribute -- not a fitted LabelEncoder?")
    return np.asarray(classes, dtype=np.int64)


def _artist_bias(source: Path, n_artists: int) -> np.ndarray:
    state_path = source / "artist_model_state.pt"
    if not state_path.exists():
        print(f"  ! {state_path.name} absent -- writing zero artist bias", file=sys.stderr)
        return np.zeros(n_artists, dtype=np.float32)
    try:
        state = torch_pickle.load(state_path)
    except Exception as exc:  # noqa: BLE001 - any read failure is non-fatal here
        print(f"  ! could not read {state_path.name} ({exc}) -- zero artist bias", file=sys.stderr)
        return np.zeros(n_artists, dtype=np.float32)

    bias = state.get("artist_bias.weight")
    if bias is None:
        print(f"  ! {state_path.name} has no artist_bias.weight -- zero bias", file=sys.stderr)
        return np.zeros(n_artists, dtype=np.float32)
    bias = np.asarray(bias, dtype=np.float32).reshape(-1)
    if bias.shape[0] != n_artists:
        print(
            f"  ! artist_bias has {bias.shape[0]} rows but there are {n_artists} artists "
            "-- the .pt file is from a different run; writing zero bias",
            file=sys.stderr,
        )
        return np.zeros(n_artists, dtype=np.float32)
    return bias


def build(source: Path, out: Path, serving: dict | None = None) -> Params:
    source, out = Path(source), Path(out)
    if not (source / "ensemble_config.json").exists():
        raise SystemExit(f"{source} is not an engine_v2 model_params folder")

    print(f"reading v2 artifacts from {source}")
    user_ids_artist = _classes(source / "user_enc_artist.pkl")
    user_ids_track = _classes(source / "track_user_enc.pkl")
    artist_ids = _classes(source / "artist_enc.pkl")
    track_ids_scored = _classes(source / "track_item_enc.pkl")

    with (source / "track_to_artist.pkl").open("rb") as fh:
        track_to_artist: dict = pickle.load(fh)
    catalogue_track_ids = np.array(sorted(int(t) for t in track_to_artist), dtype=np.int64)
    catalogue_artist_ids = np.array(
        [int(track_to_artist[int(t)]) for t in catalogue_track_ids], dtype=np.int64
    )

    v2_config = json.loads((source / "ensemble_config.json").read_text())
    arrays = {
        "artist_user_emb": np.load(source / "artist_user_embeddings.npy").astype(np.float32),
        "artist_item_emb": np.load(source / "artist_artist_embeddings.npy").astype(np.float32),
        "artist_bias": _artist_bias(source, len(artist_ids)),
        "track_user_emb": np.load(source / "track_user_embeddings.npy").astype(np.float32),
        "track_item_emb": np.load(source / "track_item_embeddings.npy").astype(np.float32),
        "track_pop": np.load(source / "track_pop.npy").astype(np.float32),
        "user_ids_artist": user_ids_artist,
        "user_ids_track": user_ids_track,
        "artist_ids": artist_ids,
        "track_ids_scored": track_ids_scored,
        "catalogue_track_ids": catalogue_track_ids,
        "catalogue_artist_ids": catalogue_artist_ids,
    }

    # Validate before writing anything: the same checks the server runs.
    params = Params(**{k: v for k, v in arrays.items()}, layout="v3")
    print("  validation passed:", json.dumps(params.stats, indent=None))

    out.mkdir(parents=True, exist_ok=True)
    for name in V3_ARRAYS:
        np.save(out / f"{name}.npy", arrays[name])

    fingerprint = _fingerprint([out / f"{n}.npy" for n in V3_ARRAYS])
    manifest = {
        "format": BUNDLE_FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source),
        "source_config": v2_config,
        "fingerprint": fingerprint,
        "stats": params.stats,
        "serving": serving
        or {
            # Carried over from the v2 export so behaviour is comparable, with
            # the R&D-only knobs left to config.py's defaults.
            "n_artist_candidates": int(v2_config.get("n_artists_candidates", 20)),
            "tracks_per_artist": int(v2_config.get("tracks_per_artist_candidate", 10)),
            "top_k_default": int(v2_config.get("top_k_final", 10)),
        },
    }
    (out / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")

    total = sum(p.stat().st_size for p in out.glob("*")) / 1e6
    print(f"wrote v3 bundle to {out} ({total:.1f} MB, {fingerprint})")
    return params


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", default="../engine_v2/model_params", help="engine_v2 model_params folder"
    )
    parser.add_argument("--out", default="model_params", help="where to write the v3 bundle")
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent.parent
    source = (here / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    out = (here / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    build(source, out)


if __name__ == "__main__":
    main()
