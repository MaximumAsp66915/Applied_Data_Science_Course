"""Loading, validating and indexing the trained artifacts.

`engine_v2/recommender.py` did all of this inline in its ``__init__``: twelve
``open()`` calls, no shape checks, no version marker, and four
``pickle.load()`` calls that pulled scikit-learn into the serving venv purely
so that ``LabelEncoder.classes_`` -- a plain integer array -- could be read
back out. If any file was missing, stale, or from a different training run
than its neighbours, the process started fine and produced quietly wrong
answers.

This module separates the two concerns that were tangled there:

* **`Params`** -- the raw arrays, plus every derived index the request path
  needs, built once at load time and never rebuilt per request.
* **`load_params`** -- getting a `Params` out of a directory, in either of
  two layouts, with real validation and a fingerprint.

Two on-disk layouts are supported:

``v3`` (preferred, produced by ``tools/build_params.py``)
    ``bundle.json`` plus a handful of ``.npy`` files. No pickles: ids are
    stored as plain integer arrays, so the serving venv needs neither
    scikit-learn nor pickle-deserialisation of files it did not write.

``v2`` (legacy, read directly from ``engine_v2/model_params/``)
    The original ``*_enc.pkl`` / ``*.npy`` layout. Works, but requires
    scikit-learn, and cannot supply the artist bias (which only exists inside
    ``artist_model_state.pt``), so stage 1 falls back to the biasless score.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

BUNDLE_FORMAT = "sutmusic-engine-params/3"
BUNDLE_MANIFEST = "bundle.json"

# Files that make up a v2 model_params/ folder, used both to detect the
# layout and to fingerprint it.
V2_FILES = (
    "ensemble_config.json",
    "user_enc_artist.pkl",
    "artist_enc.pkl",
    "track_user_enc.pkl",
    "track_item_enc.pkl",
    "track_to_artist.pkl",
    "track_id_to_idx.pkl",
    "track_pop.npy",
    "artist_user_embeddings.npy",
    "artist_artist_embeddings.npy",
    "track_user_embeddings.npy",
    "track_item_embeddings.npy",
)

V3_ARRAYS = (
    "artist_user_emb",
    "artist_item_emb",
    "artist_bias",
    "track_user_emb",
    "track_item_emb",
    "track_pop",
    "user_ids_artist",
    "user_ids_track",
    "artist_ids",
    "track_ids_scored",
    "catalogue_track_ids",
    "catalogue_artist_ids",
)


class ParamsError(RuntimeError):
    """The artifacts on disk are missing, malformed or mutually inconsistent."""


@dataclass
class Params:
    """Trained arrays plus the request-path indexes derived from them."""

    # -- stage 1: artist space ---------------------------------------------
    artist_user_emb: np.ndarray  # (n_users_artist, d_a) float32
    artist_item_emb: np.ndarray  # (n_artists, d_a)      float32
    artist_bias: np.ndarray  # (n_artists,)          float32, zeros if unknown

    # -- stage 2: track space ----------------------------------------------
    track_user_emb: np.ndarray  # (n_users_track, d_t)  float32
    track_item_emb: np.ndarray  # (n_tracks_scored, d_t) float32
    track_pop: np.ndarray  # (n_tracks_scored,)     float32

    # -- identifier axes ----------------------------------------------------
    user_ids_artist: np.ndarray  # (n_users_artist,)  int64
    user_ids_track: np.ndarray  # (n_users_track,)   int64
    artist_ids: np.ndarray  # (n_artists,)       int64
    track_ids_scored: np.ndarray  # (n_tracks_scored,) int64

    # -- catalogue (every known track, including ones with no reactions) ----
    catalogue_track_ids: np.ndarray  # (n_tracks_total,) int64
    catalogue_artist_ids: np.ndarray  # (n_tracks_total,) int64, -1 = unattributed

    layout: str = "v3"
    fingerprint: str = ""
    manifest: dict = field(default_factory=dict)

    # -- derived (built in __post_init__) -----------------------------------
    user_row_artist: dict[int, int] = field(default_factory=dict, repr=False)
    user_row_track: dict[int, int] = field(default_factory=dict, repr=False)
    artist_row: dict[int, int] = field(default_factory=dict, repr=False)
    track_row: dict[int, int] = field(default_factory=dict, repr=False)
    track_artist: dict[int, int] = field(default_factory=dict, repr=False)
    artist_tracks: dict[int, np.ndarray] = field(default_factory=dict, repr=False)
    pop_by_track: dict[int, float] = field(default_factory=dict, repr=False)
    catalogue_pop: np.ndarray = field(default=None, repr=False)
    tracks_by_popularity: np.ndarray = field(default=None, repr=False)
    artist_reach: np.ndarray = field(default=None, repr=False)
    artists_by_reach: np.ndarray = field(default=None, repr=False)
    mean_user_norm: float = 0.0

    def __post_init__(self):
        self.validate()
        self._build_indexes()

    # ---------------------------------------------------------------- checks
    def validate(self) -> None:
        """Fail loudly on artifacts that don't line up.

        Every one of these checks corresponds to a way the exports can drift
        apart when only some of the files are refreshed after a retrain --
        the failure mode engine_v2 had no defence against.
        """
        pairs = [
            ("artist_user_emb", self.artist_user_emb, "user_ids_artist", self.user_ids_artist),
            ("artist_item_emb", self.artist_item_emb, "artist_ids", self.artist_ids),
            ("track_user_emb", self.track_user_emb, "user_ids_track", self.user_ids_track),
            ("track_item_emb", self.track_item_emb, "track_ids_scored", self.track_ids_scored),
        ]
        for emb_name, emb, ids_name, ids in pairs:
            if emb.ndim != 2:
                raise ParamsError(f"{emb_name} must be 2-D, got shape {emb.shape}")
            if emb.shape[0] != ids.shape[0]:
                raise ParamsError(
                    f"{emb_name} has {emb.shape[0]} rows but {ids_name} has "
                    f"{ids.shape[0]} entries -- these files are from different runs"
                )

        if self.artist_item_emb.shape[1] != self.artist_user_emb.shape[1]:
            raise ParamsError(
                "artist user/item embedding dimensions differ "
                f"({self.artist_user_emb.shape[1]} vs {self.artist_item_emb.shape[1]})"
            )
        if self.track_item_emb.shape[1] != self.track_user_emb.shape[1]:
            raise ParamsError(
                "track user/item embedding dimensions differ "
                f"({self.track_user_emb.shape[1]} vs {self.track_item_emb.shape[1]})"
            )
        if self.artist_bias.shape != (self.artist_ids.shape[0],):
            raise ParamsError(
                f"artist_bias has shape {self.artist_bias.shape}, expected "
                f"({self.artist_ids.shape[0]},)"
            )
        if self.track_pop.shape != (self.track_ids_scored.shape[0],):
            raise ParamsError(
                f"track_pop has shape {self.track_pop.shape}, expected "
                f"({self.track_ids_scored.shape[0]},)"
            )
        if self.catalogue_track_ids.shape != self.catalogue_artist_ids.shape:
            raise ParamsError("catalogue track/artist id arrays have different lengths")
        for name, ids in (
            ("user_ids_artist", self.user_ids_artist),
            ("artist_ids", self.artist_ids),
            ("track_ids_scored", self.track_ids_scored),
            ("catalogue_track_ids", self.catalogue_track_ids),
        ):
            if len(np.unique(ids)) != len(ids):
                raise ParamsError(f"{name} contains duplicate ids")
        if not np.isfinite(self.artist_item_emb).all() or not np.isfinite(self.track_item_emb).all():
            raise ParamsError("embeddings contain NaN or inf")

        missing = set(self.track_ids_scored.tolist()) - set(self.catalogue_track_ids.tolist())
        if missing:
            raise ParamsError(
                f"{len(missing)} tracks have embeddings but are absent from the catalogue"
            )

    # --------------------------------------------------------------- indexes
    def _build_indexes(self) -> None:
        self.user_row_artist = {int(u): i for i, u in enumerate(self.user_ids_artist)}
        self.user_row_track = {int(u): i for i, u in enumerate(self.user_ids_track)}
        self.artist_row = {int(a): i for i, a in enumerate(self.artist_ids)}
        self.track_row = {int(t): i for i, t in enumerate(self.track_ids_scored)}
        self.track_artist = {
            int(t): int(a)
            for t, a in zip(self.catalogue_track_ids, self.catalogue_artist_ids)
        }

        # Popularity for every catalogue track, 0 for tracks nobody has
        # reacted to yet. Keeping those tracks addressable is what lets the
        # engine recommend them at all (engine_v2 could not).
        pop_lookup = np.zeros(len(self.catalogue_track_ids), dtype=np.float32)
        rows = np.array(
            [self.track_row.get(int(t), -1) for t in self.catalogue_track_ids], dtype=np.int64
        )
        known = rows >= 0
        pop_lookup[known] = self.track_pop[rows[known]]
        self.catalogue_pop = pop_lookup

        # artist row -> its track ids, most popular first. Sorting once here
        # is what makes "top N tracks for this artist" an O(1) slice per
        # request instead of a sort.
        order = np.argsort(-pop_lookup, kind="stable")
        artist_of = self.catalogue_artist_ids[order]
        track_of = self.catalogue_track_ids[order]
        buckets: dict[int, list[int]] = {}
        for artist_id, track_id in zip(artist_of.tolist(), track_of.tolist()):
            row = self.artist_row.get(artist_id)
            if row is None:  # -1 (unattributed) or an artist that never trained
                continue
            buckets.setdefault(row, []).append(track_id)
        self.artist_tracks = {r: np.array(v, dtype=np.int64) for r, v in buckets.items()}

        self.tracks_by_popularity = track_of.astype(np.int64, copy=True)

        # Onboarding order over artists. engine_v2 ranked artists by the SUM
        # of their tracks' popularity, which just surfaces whoever has the
        # biggest catalogue; the max is a better "is this artist actually a
        # crowd-pleaser" signal for a first-session pick.
        # Each artist_tracks list is already popularity-sorted, so the first
        # entry is that artist's best track.
        self.pop_by_track = {int(t): float(p) for t, p in zip(self.catalogue_track_ids, pop_lookup)}
        reach = np.zeros(len(self.artist_ids), dtype=np.float32)
        for row, tracks in self.artist_tracks.items():
            if len(tracks):
                reach[row] = self.pop_by_track[int(tracks[0])]
        self.artist_reach = reach
        self.artists_by_reach = np.argsort(-reach, kind="stable")

        norms = np.linalg.norm(self.artist_user_emb, axis=1)
        self.mean_user_norm = float(norms[norms > 0].mean()) if (norms > 0).any() else 1.0

    # ----------------------------------------------------------------- stats
    @property
    def stats(self) -> dict:
        n_unscored = len(self.catalogue_track_ids) - len(self.track_ids_scored)
        return {
            "n_users_artist": int(len(self.user_ids_artist)),
            "n_users_track": int(len(self.user_ids_track)),
            "n_artists": int(len(self.artist_ids)),
            "n_tracks_total": int(len(self.catalogue_track_ids)),
            "n_tracks_scored": int(len(self.track_ids_scored)),
            "n_tracks_unscored": int(n_unscored),
            "n_artists_with_tracks": int(len(self.artist_tracks)),
            "artist_embedding_dim": int(self.artist_item_emb.shape[1]),
            "track_embedding_dim": int(self.track_item_emb.shape[1]),
            "has_artist_bias": bool(np.any(self.artist_bias)),
        }


# --------------------------------------------------------------------- load


def _fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.exists():
            continue
        digest.update(path.name.encode())
        digest.update(str(path.stat().st_size).encode())
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()[:16]}"


def detect_layout(params_dir: Path) -> str:
    if (params_dir / BUNDLE_MANIFEST).exists():
        return "v3"
    if (params_dir / "ensemble_config.json").exists():
        return "v2"
    raise ParamsError(
        f"{params_dir} looks like neither a v3 bundle (no {BUNDLE_MANIFEST}) nor a "
        "v2 model_params folder (no ensemble_config.json)"
    )


def _load_v3(params_dir: Path) -> Params:
    manifest = json.loads((params_dir / BUNDLE_MANIFEST).read_text())
    if manifest.get("format") != BUNDLE_FORMAT:
        raise ParamsError(
            f"unsupported bundle format {manifest.get('format')!r}, expected {BUNDLE_FORMAT!r}"
        )
    arrays = {}
    for name in V3_ARRAYS:
        path = params_dir / f"{name}.npy"
        if not path.exists():
            raise ParamsError(f"bundle is missing {path.name}")
        arrays[name] = np.load(path)

    return Params(
        artist_user_emb=arrays["artist_user_emb"].astype(np.float32, copy=False),
        artist_item_emb=arrays["artist_item_emb"].astype(np.float32, copy=False),
        artist_bias=arrays["artist_bias"].astype(np.float32, copy=False).reshape(-1),
        track_user_emb=arrays["track_user_emb"].astype(np.float32, copy=False),
        track_item_emb=arrays["track_item_emb"].astype(np.float32, copy=False),
        track_pop=arrays["track_pop"].astype(np.float32, copy=False).reshape(-1),
        user_ids_artist=arrays["user_ids_artist"].astype(np.int64, copy=False),
        user_ids_track=arrays["user_ids_track"].astype(np.int64, copy=False),
        artist_ids=arrays["artist_ids"].astype(np.int64, copy=False),
        track_ids_scored=arrays["track_ids_scored"].astype(np.int64, copy=False),
        catalogue_track_ids=arrays["catalogue_track_ids"].astype(np.int64, copy=False),
        catalogue_artist_ids=arrays["catalogue_artist_ids"].astype(np.int64, copy=False),
        layout="v3",
        fingerprint=manifest.get("fingerprint", ""),
        manifest=manifest,
    )


def _load_v2(params_dir: Path) -> Params:
    """Read the original engine_v2 layout in place, for A/B comparison.

    Needs scikit-learn (the encoders are pickled ``LabelEncoder`` objects) and
    cannot recover the artist bias, which lives only in the ``.pt`` state
    dict. ``tools/build_params.py`` exists to get rid of both limitations.
    """
    import pickle  # local: only the legacy path unpickles anything

    def read_pickle(name: str):
        with (params_dir / name).open("rb") as fh:
            return pickle.load(fh)

    try:
        user_enc_artist = read_pickle("user_enc_artist.pkl")
        artist_enc = read_pickle("artist_enc.pkl")
        track_user_enc = read_pickle("track_user_enc.pkl")
        track_item_enc = read_pickle("track_item_enc.pkl")
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on venv
        raise ParamsError(
            "reading the legacy v2 layout requires scikit-learn (the encoders are "
            "pickled LabelEncoder objects). Convert the folder first with "
            "tools/build_params.py to drop that dependency."
        ) from exc

    track_to_artist: dict = read_pickle("track_to_artist.pkl")
    config = json.loads((params_dir / "ensemble_config.json").read_text())

    catalogue = sorted(int(t) for t in track_to_artist)
    return Params(
        artist_user_emb=np.load(params_dir / "artist_user_embeddings.npy"),
        artist_item_emb=np.load(params_dir / "artist_artist_embeddings.npy"),
        artist_bias=np.zeros(len(artist_enc.classes_), dtype=np.float32),
        track_user_emb=np.load(params_dir / "track_user_embeddings.npy"),
        track_item_emb=np.load(params_dir / "track_item_embeddings.npy"),
        track_pop=np.load(params_dir / "track_pop.npy").astype(np.float32),
        user_ids_artist=np.asarray(user_enc_artist.classes_, dtype=np.int64),
        user_ids_track=np.asarray(track_user_enc.classes_, dtype=np.int64),
        artist_ids=np.asarray(artist_enc.classes_, dtype=np.int64),
        track_ids_scored=np.asarray(track_item_enc.classes_, dtype=np.int64),
        catalogue_track_ids=np.array(catalogue, dtype=np.int64),
        catalogue_artist_ids=np.array(
            [int(track_to_artist[t]) for t in catalogue], dtype=np.int64
        ),
        layout="v2",
        fingerprint=_fingerprint([params_dir / n for n in V2_FILES]),
        manifest={"format": "engine_v2/model_params", "serving": config},
    )


def load_params(params_dir: str | Path) -> Params:
    """Load whichever layout is in ``params_dir``."""
    params_dir = Path(params_dir)
    if not params_dir.is_dir():
        raise ParamsError(f"parameter directory {params_dir} does not exist")

    layout = detect_layout(params_dir)
    params = _load_v3(params_dir) if layout == "v3" else _load_v2(params_dir)
    if layout == "v2":
        log.warning(
            "loaded legacy v2 artifacts from %s: no artist bias available, stage-1 "
            "ranking will not match the trained scoring function. Run "
            "tools/build_params.py to produce a v3 bundle.",
            params_dir,
        )
    log.info("loaded %s params from %s (%s): %s", layout, params_dir, params.fingerprint, params.stats)
    return params


def resolve_params_dir(base_dir: Path, explicit: str | None = None) -> Path:
    """Pick the parameter directory: env/CLI override, local bundle, then the
    in-repo engine_v2 folder so a fresh checkout runs without a build step."""
    if explicit:
        return Path(explicit).expanduser().resolve()

    local = base_dir / "model_params"
    if (local / BUNDLE_MANIFEST).exists() or (local / "ensemble_config.json").exists():
        return local

    legacy = base_dir.parent / "engine_v2" / "model_params"
    if (legacy / "ensemble_config.json").exists():
        log.warning(
            "no bundle in %s; falling back to the read-only engine_v2 artifacts at %s",
            local,
            legacy,
        )
        return legacy
    return local
