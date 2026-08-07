"""Artifact loading, validation and index construction.

The validation tests matter more than they look: every mismatch checked here
is a state ``engine_v2`` would have loaded without complaint and then served
wrong answers from, because a retrain that refreshes some exports and not
others leaves exactly these inconsistencies behind.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from artifacts import BUNDLE_FORMAT, V3_ARRAYS, Params, ParamsError, load_params, resolve_params_dir
from tests.conftest import DEEP, QUIET, SHALLOW


def _kwargs(params: Params) -> dict:
    """The constructor arguments of an existing Params, for mutation in tests."""
    names = (
        "artist_user_emb artist_item_emb artist_bias track_user_emb track_item_emb "
        "track_pop user_ids_artist user_ids_track artist_ids track_ids_scored "
        "catalogue_track_ids catalogue_artist_ids"
    ).split()
    return {n: getattr(params, n) for n in names}


class TestValidation:
    def test_row_count_mismatch_is_rejected(self, params):
        kwargs = _kwargs(params)
        kwargs["artist_ids"] = kwargs["artist_ids"][:-1]
        with pytest.raises(ParamsError, match="different runs"):
            Params(**kwargs)

    def test_embedding_dimension_mismatch_is_rejected(self, params):
        kwargs = _kwargs(params)
        kwargs["artist_user_emb"] = kwargs["artist_user_emb"][:, :-1]
        with pytest.raises(ParamsError, match="dimensions differ"):
            Params(**kwargs)

    def test_wrong_length_bias_is_rejected(self, params):
        kwargs = _kwargs(params)
        kwargs["artist_bias"] = np.zeros(99, dtype=np.float32)
        with pytest.raises(ParamsError, match="artist_bias"):
            Params(**kwargs)

    def test_duplicate_ids_are_rejected(self, params):
        kwargs = _kwargs(params)
        kwargs["artist_ids"] = np.array([DEEP, DEEP, QUIET], dtype=np.int64)
        with pytest.raises(ParamsError, match="duplicate ids"):
            Params(**kwargs)

    def test_nan_embeddings_are_rejected(self, params):
        kwargs = _kwargs(params)
        broken = kwargs["artist_item_emb"].copy()
        broken[0, 0] = np.nan
        kwargs["artist_item_emb"] = broken
        with pytest.raises(ParamsError, match="NaN"):
            Params(**kwargs)

    def test_scored_track_missing_from_catalogue_is_rejected(self, params):
        kwargs = _kwargs(params)
        kwargs["catalogue_track_ids"] = kwargs["catalogue_track_ids"][1:]
        kwargs["catalogue_artist_ids"] = kwargs["catalogue_artist_ids"][1:]
        with pytest.raises(ParamsError, match="absent from the catalogue"):
            Params(**kwargs)


class TestIndexes:
    def test_artist_tracks_are_popularity_sorted(self, params):
        row = params.artist_row[DEEP]
        pops = [params.pop_by_track[int(t)] for t in params.artist_tracks[row]]
        assert pops == sorted(pops, reverse=True)

    def test_unscored_tracks_get_zero_popularity_not_dropped(self, params):
        assert params.pop_by_track[301] == 0.0
        assert 301 in {int(t) for t in params.artist_tracks[params.artist_row[QUIET]]}

    def test_untrained_artist_contributes_no_bucket(self, params):
        """Artist 40 is in the catalogue but was never trained, so there is no
        embedding to rank it with and no bucket to draw from."""
        assert 40 not in params.artist_row
        assert 400 not in {t for tracks in params.artist_tracks.values() for t in tracks}

    def test_artist_reach_uses_best_track_not_catalogue_size(self, params):
        """engine_v2 ranked onboarding artists by the SUM of their tracks'
        popularity, which is mostly a measure of catalogue size."""
        assert params.artist_reach[params.artist_row[DEEP]] == 20.0
        assert params.artist_reach[params.artist_row[SHALLOW]] == 5.0

    def test_stats_report_the_unscored_split(self, params):
        stats = params.stats
        assert stats["n_tracks_total"] == stats["n_tracks_scored"] + stats["n_tracks_unscored"]
        assert stats["n_tracks_unscored"] == 3  # 301, 400, 999


class TestBundleRoundTrip:
    def test_written_bundle_loads_back_identically(self, params, tmp_path):
        for name in V3_ARRAYS:
            np.save(tmp_path / f"{name}.npy", getattr(params, name))
        (tmp_path / "bundle.json").write_text(
            json.dumps({"format": BUNDLE_FORMAT, "fingerprint": "sha256:test", "serving": {}})
        )

        loaded = load_params(tmp_path)
        assert loaded.layout == "v3"
        assert loaded.stats == params.stats
        assert np.array_equal(loaded.catalogue_track_ids, params.catalogue_track_ids)

    def test_unknown_format_is_rejected(self, tmp_path):
        (tmp_path / "bundle.json").write_text(json.dumps({"format": "something-else/9"}))
        with pytest.raises(ParamsError, match="unsupported bundle format"):
            load_params(tmp_path)

    def test_missing_array_is_reported_by_name(self, tmp_path, params):
        (tmp_path / "bundle.json").write_text(json.dumps({"format": BUNDLE_FORMAT}))
        np.save(tmp_path / "artist_user_emb.npy", params.artist_user_emb)
        with pytest.raises(ParamsError, match="missing"):
            load_params(tmp_path)

    def test_empty_directory_is_reported_clearly(self, tmp_path):
        with pytest.raises(ParamsError, match="neither a v3 bundle"):
            load_params(tmp_path)

    def test_nonexistent_directory_is_reported_clearly(self, tmp_path):
        with pytest.raises(ParamsError, match="does not exist"):
            load_params(tmp_path / "nope")


class TestResolution:
    def test_explicit_path_wins(self, tmp_path):
        assert resolve_params_dir(tmp_path, str(tmp_path / "chosen")) == tmp_path / "chosen"

    def test_local_bundle_is_preferred(self, tmp_path):
        (tmp_path / "model_params").mkdir()
        (tmp_path / "model_params" / "bundle.json").write_text("{}")
        assert resolve_params_dir(tmp_path) == tmp_path / "model_params"
