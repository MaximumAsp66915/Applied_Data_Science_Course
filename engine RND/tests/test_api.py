"""HTTP contract tests.

The single most important property of this service is that
``app/webapp/engine_client.py`` cannot tell it apart from engine_v2. The first
class below pins that down field by field; the rest cover the behaviour that
was missing -- structured errors instead of tracebacks, and a health endpoint
that reports a failed load rather than pretending everything is fine.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

import main
from artifacts import BUNDLE_FORMAT, V3_ARRAYS


@pytest.fixture
def bundle_dir(params, tmp_path):
    for name in V3_ARRAYS:
        np.save(tmp_path / f"{name}.npy", getattr(params, name))
    (tmp_path / "bundle.json").write_text(
        json.dumps(
            {
                "format": BUNDLE_FORMAT,
                "fingerprint": "sha256:test",
                "serving": {"n_artist_candidates": 2, "tracks_per_artist": 3,
                            "explore_temperature": 0.0},
            }
        )
    )
    return tmp_path


@pytest.fixture
def client(bundle_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("ENGINE_PARAMS_DIR", str(bundle_dir))
    # Keep the learning layer's state out of the working tree: a test run must
    # not leave an event log or a trained bandit behind in the repository.
    monkeypatch.setenv("ENGINE_LEARN_STATE_DIR", str(tmp_path / "learn"))
    # Pin the exploration slice off so the contract tests are deterministic.
    # In production ~10% of requests deliberately take a different arm, which
    # would otherwise make "these two calls agree" a flaky assertion.
    monkeypatch.setenv("ENGINE_LEARN_EXPLORE_SHARE", "0")
    with TestClient(main.app) as test_client:
        yield test_client


class TestEngineV2Contract:
    """Every field engine_v2 returned, still returned, with the same meaning."""

    def test_health_keeps_v2_fields(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert {"n_users", "n_artists", "n_tracks"} <= body.keys()
        assert all(isinstance(body[k], int) for k in ("n_users", "n_artists", "n_tracks"))

    def test_suggest_shape(self, client):
        body = client.get("/suggest", params={"user_id": 1}).json()
        assert isinstance(body["track_id"], int)
        assert isinstance(body["reason"], str)
        assert body["source"] in (
            "trained_embedding", "blended_profile", "reacted_artists",
            "reacted_tracks", "popular_fallback",
        )

    def test_recommend_shape(self, client):
        body = client.get("/recommend", params={"user_id": 1, "top_k": 4}).json()
        assert isinstance(body["track_ids"], list)
        assert len(body["track_ids"]) <= 4
        assert all(isinstance(t, int) for t in body["track_ids"])
        assert isinstance(body["source"], str)

    def test_onboarding_shape(self, client):
        body = client.get("/onboarding", params={"count": 2}).json()
        assert isinstance(body["track_ids"], list) and len(body["track_ids"]) <= 2

    def test_unknown_user_falls_back_instead_of_failing(self, client):
        body = client.get("/recommend", params={"user_id": 99999}).json()
        assert body["source"] == "popular_fallback"
        assert body["track_ids"]

    def test_no_parameters_at_all_still_answers(self, client):
        assert client.get("/suggest").status_code == 200

    def test_exclusions_are_honoured(self, client):
        first = client.get("/recommend", params={"user_id": 1, "top_k": 3}).json()["track_ids"]
        second = client.get(
            "/recommend",
            params={"user_id": 1, "top_k": 3, "exclude_track_ids": ",".join(map(str, first))},
        ).json()["track_ids"]
        assert not set(first) & set(second)

    def test_top_k_bounds_are_enforced(self, client):
        assert client.get("/recommend", params={"top_k": 0}).status_code == 422
        assert client.get("/recommend", params={"top_k": 51}).status_code == 422


class TestErrorHandling:
    def test_malformed_id_list_is_a_422_not_a_500(self, client):
        """engine_v2 called int() straight on the query string, so this was an
        unhandled ValueError and a 500 with a traceback."""
        response = client.get("/suggest", params={"exclude_track_ids": "12,not-an-id"})
        assert response.status_code == 422
        assert "exclude_track_ids" in response.json()["detail"]

    def test_absurdly_long_id_list_is_rejected(self, client):
        ids = ",".join(str(i) for i in range(5000))
        assert client.get("/suggest", params={"exclude_track_ids": ids}).status_code == 422

    def test_empty_and_trailing_commas_are_tolerated(self, client):
        assert client.get("/suggest", params={"exclude_track_ids": "100,,101,"}).status_code == 200

    def test_negative_and_unknown_ids_are_ignored_not_fatal(self, client):
        body = client.get(
            "/recommend", params={"reacted_artist_ids": "-5,987654", "top_k": 2}
        ).json()
        assert body["source"] == "popular_fallback"


class TestDegradedStart:
    def test_missing_artifacts_report_503_rather_than_crashing(self, tmp_path, monkeypatch):
        """engine_v2 raised inside its lifespan handler; anything that got
        through answered every request with a KeyError on `state["rec"]`."""
        monkeypatch.setenv("ENGINE_LEARN_STATE_DIR", str(tmp_path / "learn"))
        monkeypatch.setenv("ENGINE_PARAMS_DIR", str(tmp_path / "absent"))
        with TestClient(main.app, raise_server_exceptions=False) as client:
            health = client.get("/health")
            assert health.status_code == 503
            assert health.json()["status"] == "degraded"
            assert client.get("/suggest").status_code == 503
            assert client.get("/recommend").status_code == 503


class TestNewEndpoints:
    def test_explain_exposes_the_intermediate_stages(self, client):
        body = client.get("/explain", params={"user_id": 1, "top_k": 3}).json()
        assert body["profile"]["has_artist_vector"] is True
        assert body["top_artists"]
        assert {"artist_id", "score", "catalogue_size"} <= body["top_artists"][0].keys()
        assert "widen_steps" in body and "pool_size" in body

    def test_explain_ranking_matches_recommend(self, client):
        params = {"user_id": 1, "top_k": 3}
        assert (
            client.get("/explain", params=params).json()["track_ids"]
            == client.get("/recommend", params=params).json()["track_ids"]
        )

    def test_health_reports_what_is_loaded(self, client):
        body = client.get("/health").json()
        assert body["layout"] == "v3"
        assert body["fingerprint"] == "sha256:test"
        assert body["config"]["n_artist_candidates"] == 2  # from the bundle manifest


class TestLiveSignal:
    def test_reacted_artists_are_used_alongside_a_known_user(self, client):
        """engine_v2 discarded reacted_* whenever user_id resolved."""
        plain = client.get("/recommend", params={"user_id": 1, "top_k": 5}).json()
        with_signal = client.get(
            "/recommend", params={"user_id": 1, "reacted_artist_ids": "20", "top_k": 5}
        ).json()
        assert with_signal["source"] == "blended_profile"
        assert plain["source"] == "trained_embedding"


class TestLearningEndpoints:
    """The feedback loop over HTTP. See `algorithm improvement/README.md`."""

    def test_learning_reports_the_arm_registry_and_mode(self, client):
        body = client.get("/learning").json()
        assert body["enabled"] is True
        assert body["bandit"]["mode"] == "shadow"
        assert {p["name"] for p in body["policies"]} >= {"exploit", "discover", "diversify"}

    def test_health_carries_a_learning_summary(self, client):
        summary = client.get("/health").json()["learning"]
        assert summary["enabled"] is True
        assert "attribution_rate" in summary

    def test_feedback_on_a_served_track_is_attributed(self, client):
        track_id = client.get("/suggest", params={"user_id": 1}).json()["track_id"]
        body = client.post(
            "/feedback",
            json={"user_id": 1, "track_id": track_id, "outcome": "completed"},
        ).json()
        assert body["attributed"] is True
        assert body["reward"] > 0

    def test_feedback_on_a_track_we_never_served_is_not_attributed(self, client):
        body = client.post(
            "/feedback", json={"user_id": 1, "track_id": 987654, "outcome": "completed"}
        ).json()
        assert body["attributed"] is False

    def test_feedback_validates_its_input(self, client):
        assert client.post("/feedback", json={"user_id": 1}).status_code == 422
        assert client.post(
            "/feedback", json={"track_id": 1, "outcome": "vibed"}
        ).status_code == 422
        assert client.post(
            "/feedback", json={"track_id": "abc", "outcome": "completed"}
        ).status_code == 422

    def test_implicit_hints_train_the_loop_through_suggest(self, client):
        """No app change required: /suggest already carries these parameters."""
        first = client.get("/suggest", params={"user_id": 1}).json()["track_id"]
        client.get(
            "/suggest", params={"user_id": 1, "implicit_liked_track_id": first}
        )
        learning = client.get("/learning").json()
        assert learning["counters"]["outcomes_attributed"] >= 1

    def test_suggest_reports_which_policy_served_the_pick(self, client):
        body = client.get("/suggest", params={"user_id": 1}).json()
        assert body["policy"] in {p["name"] for p in client.get("/learning").json()["policies"]}

    def test_explain_shows_the_policy_and_personalisation(self, client):
        body = client.get("/explain", params={"user_id": 1, "top_k": 3}).json()
        assert body["learning"]["policy"] is not None
        assert body["learning"]["personalised"] is False  # user deltas off by default

    def test_snapshot_can_be_forced(self, client):
        assert client.post("/learning/snapshot").json()["saved"] is True

    def test_state_survives_a_restart_of_the_service(self, bundle_dir, monkeypatch, tmp_path):
        """Learning that evaporates on deploy is not learning."""
        state = tmp_path / "learn"
        monkeypatch.setenv("ENGINE_PARAMS_DIR", str(bundle_dir))
        monkeypatch.setenv("ENGINE_LEARN_STATE_DIR", str(state))
        monkeypatch.setenv("ENGINE_LEARN_EXPLORE_SHARE", "0")

        with TestClient(main.app) as first:
            track_id = first.get("/suggest", params={"user_id": 1}).json()["track_id"]
            first.post(
                "/feedback",
                json={"user_id": 1, "track_id": track_id, "outcome": "completed"},
            )
            before = first.get("/learning").json()["bandit"]["total_updates"]
        assert before >= 1

        with TestClient(main.app) as second:
            assert second.get("/learning").json()["bandit"]["total_updates"] == before


class TestLearningDisabled:
    def test_the_engine_serves_normally_with_learning_switched_off(
        self, bundle_dir, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("ENGINE_PARAMS_DIR", str(bundle_dir))
        monkeypatch.setenv("ENGINE_LEARN_ENABLED", "0")
        with TestClient(main.app) as client:
            assert client.get("/suggest", params={"user_id": 1}).status_code == 200
            assert "policy" not in client.get("/suggest", params={"user_id": 1}).json()
            assert client.get("/learning").json()["enabled"] is False
            assert client.post(
                "/feedback", json={"track_id": 1, "outcome": "completed"}
            ).status_code == 503
            assert client.get("/health").json()["learning"] == {"enabled": False}
