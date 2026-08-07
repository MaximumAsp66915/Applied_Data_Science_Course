"""End-to-end conversion of the real engine_v2 artifacts.

Skipped automatically when ``engine_v2/model_params/`` is not present. When it
is, this is the strongest check in the suite: it reads the ``.pt`` state dicts
without torch and proves the reconstruction is bit-for-bit identical to the
``.npy`` files the training notebook exported alongside them.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from artifacts import BUNDLE_FORMAT, load_params
from tools import torch_pickle
from tools.build_params import build

V2_DIR = Path(__file__).resolve().parent.parent.parent / "engine_v2" / "model_params"

pytestmark = pytest.mark.skipif(
    not (V2_DIR / "ensemble_config.json").exists(),
    reason="engine_v2/model_params not available",
)


class TestTorchFreeReader:
    def test_reconstructs_the_exported_artist_embeddings_exactly(self):
        """artist_embedding = artist_id_emb + genre_proj(genre_features).

        If this matches the separately-exported .npy to the bit, the reader is
        interpreting torch's storage layout correctly -- which is what makes
        recovering the un-exported bias trustworthy.
        """
        state = torch_pickle.load(V2_DIR / "artist_model_state.pt")
        genre = torch_pickle.load(V2_DIR / "genre_features.pt")
        rebuilt = state["artist_id_emb.weight"] + genre @ state["genre_proj.weight"].T
        exported = np.load(V2_DIR / "artist_artist_embeddings.npy")
        assert np.array_equal(rebuilt, exported)

    def test_reconstructs_the_exported_user_embeddings_exactly(self):
        state = torch_pickle.load(V2_DIR / "artist_model_state.pt")
        assert np.array_equal(
            state["user_emb.weight"], np.load(V2_DIR / "artist_user_embeddings.npy")
        )

    def test_track_model_matches_its_exports(self):
        state = torch_pickle.load(V2_DIR / "track_model_state.pt")
        assert np.array_equal(
            state["item_emb.weight"], np.load(V2_DIR / "track_item_embeddings.npy")
        )

    def test_artist_bias_is_recoverable_and_non_trivial(self):
        """The term engine_v2 could not serve with. If it were all zeros there
        would be nothing to recover and [FIX 3] would be pointless."""
        bias = torch_pickle.load(V2_DIR / "artist_model_state.pt")["artist_bias.weight"]
        assert bias.shape[0] == 5107
        assert float(bias.std()) > 0.1

    def test_user_bias_is_dead_weight(self, capsys):
        """Documented, not fixed here: in a BPR objective the user bias appears
        in both the positive and the negative score and cancels in their
        difference, so it never receives a gradient. It is still all zeros
        after 100 epochs of training."""
        state = torch_pickle.load(V2_DIR / "artist_model_state.pt")
        assert not np.any(state["user_bias.weight"])


class TestConversion:
    def test_produces_a_loadable_validated_bundle(self, tmp_path):
        built = build(V2_DIR, tmp_path)
        loaded = load_params(tmp_path)

        assert loaded.layout == "v3"
        assert loaded.manifest["format"] == BUNDLE_FORMAT
        assert loaded.stats == built.stats
        assert loaded.stats["has_artist_bias"] is True

    def test_bundle_contains_no_pickles(self, tmp_path):
        """The point of the conversion: nothing at serve time is unpickled,
        and scikit-learn leaves the serving venv."""
        build(V2_DIR, tmp_path)
        assert not list(tmp_path.glob("*.pkl"))
        assert {p.suffix for p in tmp_path.iterdir()} == {".npy", ".json"}

    def test_ids_survive_the_encoder_round_trip(self, tmp_path):
        build(V2_DIR, tmp_path)
        loaded = load_params(tmp_path)
        # Known values from the shipped artifacts.
        assert len(loaded.artist_ids) == 5107
        assert len(loaded.user_ids_artist) == 1310
        assert len(loaded.catalogue_track_ids) == 14843

    def test_source_directory_is_left_untouched(self, tmp_path):
        before = {p.name: p.stat().st_mtime_ns for p in V2_DIR.iterdir()}
        build(V2_DIR, tmp_path)
        after = {p.name: p.stat().st_mtime_ns for p in V2_DIR.iterdir()}
        assert before == after

    def test_rejects_a_directory_that_is_not_v2(self, tmp_path):
        with pytest.raises(SystemExit):
            build(tmp_path, tmp_path / "out")
