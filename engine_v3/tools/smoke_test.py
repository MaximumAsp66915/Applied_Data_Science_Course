"""End-to-end smoke test of a RUNNING engine (local or on the server).

    python tools/smoke_test.py --base-url http://127.0.0.1:8100 --params-dir model_params

Checks the HTTP contract app/webapp/engine_client.py depends on -- response
shapes, exclusion being honoured, every fallback path, input validation,
determinism, and request latency -- using real ids read from the same
model_params/ folder the engine loaded. Exits non-zero on any failure.
Needs only `httpx` and numpy/scikit-learn (the engine's own pins).
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import statistics
import sys
import time
from pathlib import Path

import httpx

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def load(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8100")
    ap.add_argument("--params-dir", type=Path, default=Path(__file__).resolve().parents[1] / "model_params")
    ap.add_argument("--latency-calls", type=int, default=200)
    a = ap.parse_args()
    p = a.params_dir
    cfg = json.loads((p / "ensemble_config.json").read_text())
    users = [int(u) for u in load(p / "user_enc_artist.pkl").classes_]
    track_ids = [int(t) for t in load(p / "track_item_enc.pkl").classes_]
    artists = [int(x) for x in load(p / "artist_enc.pkl").classes_]
    t2a = load(p / "track_to_artist.pkl")
    alias = load(p / "artist_alias.pkl") if (p / "artist_alias.pkl").exists() else {}
    universe = set(track_ids)
    rnd = random.Random(7)
    c = httpx.Client(base_url=a.base_url, timeout=10)

    print("/health")
    h = c.get("/health")
    j = h.json()
    check("200 + status ok", h.status_code == 200 and j.get("status") == "ok")
    check("counts match model_params", (j["n_users"], j["n_artists"], j["n_tracks"]) == (len(users), len(artists), len(track_ids)), str(j))
    check("reports model_version", j.get("model_version") == cfg.get("model_version"), str(j))

    print("/suggest")
    u = rnd.choice(users)
    r = c.get("/suggest", params={"user_id": u})
    j = r.json()
    check("known user -> 200 with track_id/reason/source", r.status_code == 200 and {"track_id", "reason", "source"} <= set(j), str(j))
    check("known user -> trained_embedding source, track in universe", j.get("source") == "trained_embedding" and j.get("track_id") in universe, str(j))
    first = j["track_id"]
    r = c.get("/suggest", params={"user_id": u, "exclude_track_ids": str(first)})
    check("exclude_track_ids is honoured", r.status_code == 200 and r.json()["track_id"] != first)
    r = c.get("/suggest", params={"user_id": u})
    check("deterministic for identical requests", r.json()["track_id"] == first)
    r = c.get("/suggest")
    check("no signal at all -> popular_fallback", r.status_code == 200 and r.json().get("source") == "popular_fallback", r.text)
    r = c.get("/suggest", params={"user_id": 1, "reacted_artist_ids": ",".join(map(str, artists[:3]))})
    check("unknown user + reacted artists -> reacted_artists", r.json().get("source") == "reacted_artists", r.text)
    r = c.get("/suggest", params={"user_id": 1, "reacted_track_ids": ",".join(map(str, track_ids[:3]))})
    check("unknown user + reacted tracks -> reacted_tracks", r.json().get("source") in ("reacted_tracks", "reacted_artists"), r.text)
    if alias:
        dup = next(iter(alias))
        r = c.get("/suggest", params={"user_id": 1, "reacted_artist_ids": str(dup)})
        check("merged duplicate artist id is recognised (alias)", r.json().get("source") == "reacted_artists", r.text)
    r = c.get("/suggest", params={"user_id": u, "implicit_liked_track_id": track_ids[10], "implicit_disliked_track_id": track_ids[20]})
    check("implicit like/dislike nudge accepted", r.status_code == 200 and "track_id" in r.json(), r.text)
    big = rnd.sample(track_ids, 8000)  # a heavy listener's history; a query string can't carry much more than this
    r = c.get("/suggest", params={"user_id": u, "exclude_track_ids": ",".join(map(str, big))})
    check("8000 excluded ids -> still a valid, non-excluded pick", r.status_code == 200 and r.json()["track_id"] not in set(big), f"{r.status_code} {r.text[:120]}")
    r = c.get("/suggest", params={"user_id": "abc"})
    check("garbage user_id -> 422", r.status_code == 422, str(r.status_code))

    print("/recommend")
    ex = rnd.sample(track_ids, 100)
    r = c.get("/recommend", params={"user_id": u, "top_k": 10, "exclude_track_ids": ",".join(map(str, ex))})
    ids = r.json().get("track_ids", [])
    check("10 unique ids, none excluded, all in universe", len(ids) == 10 and len(set(ids)) == 10 and not set(ids) & set(ex) and set(ids) <= universe, str(ids))
    r1 = c.get("/recommend", params={"user_id": u, "top_k": 1, "exclude_track_ids": ",".join(map(str, ex))})
    r2 = c.get("/suggest", params={"user_id": u, "exclude_track_ids": ",".join(map(str, ex))})
    check("/suggest == first of /recommend", r1.json()["track_ids"] == [r2.json()["track_id"]] and r1.json()["track_ids"][0] == ids[0])
    r = c.get("/recommend", params={"user_id": u, "top_k": 50})
    check("top_k=50 ok", r.status_code == 200 and len(r.json()["track_ids"]) == 50)
    check("top_k=51 rejected (422)", c.get("/recommend", params={"top_k": 51}).status_code == 422)
    check("top_k=0 rejected (422)", c.get("/recommend", params={"top_k": 0}).status_code == 422)

    print("/onboarding")
    r = c.get("/onboarding", params={"count": 5})
    ids = r.json().get("track_ids", [])
    arts = {t2a.get(t) for t in ids}
    check("5 tracks from 5 different artists", len(ids) == 5 and len(arts) == 5, str(ids))
    r = c.get("/onboarding", params={"count": 5, "exclude_track_ids": ",".join(map(str, ids))})
    check("exclude honoured", not set(r.json()["track_ids"]) & set(ids))
    check("count=21 rejected (422)", c.get("/onboarding", params={"count": 21}).status_code == 422)

    print(f"latency ({a.latency_calls} /suggest calls, ~100 excluded ids each)")
    ms = []
    for _ in range(a.latency_calls):
        uu = rnd.choice(users)
        ex = ",".join(map(str, rnd.sample(track_ids, 100)))
        t0 = time.perf_counter()
        rr = c.get("/suggest", params={"user_id": uu, "exclude_track_ids": ex})
        ms.append((time.perf_counter() - t0) * 1000)
        if rr.status_code != 200:
            failures.append(f"latency loop got {rr.status_code}")
            break
    ms.sort()
    p50, p95 = statistics.median(ms), ms[int(len(ms) * 0.95) - 1]
    print(f"  p50={p50:.1f} ms  p95={p95:.1f} ms  max={ms[-1]:.1f} ms")
    check("p95 latency < 250 ms", p95 < 250, f"p95={p95:.0f}ms")

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
