"""Score engine_v1, engine_v2 and a freshly trained v3 on the SAME out-of-time test.

    python tools/compare_engines.py --data-dir <csv dir> --v3-dir <model_params trained with --split temporal>

Protocol (identical for every engine): train data = reactions before --cutoff,
test = positive reactions on/after it. For each test user who has history before
the cutoff, every engine recommends its top 10 with the tracks that user already
reacted to / uploaded and the tracks that did not exist yet at the cutoff excluded;
we measure how many of the user's real later likes show up. Only users that ALL
engines know are scored, so nobody is penalised for a user it never saw.

v1 and v2 were trained once, around Aug 7, from the data available then -- they
have never seen a reaction after the cutoff, so the test is genuinely out-of-time
for them too. Each engine runs with its own shipped default settings.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_v3"))
import train as T  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--v3-dir", required=True, type=Path)
    ap.add_argument("--cutoff", default="2026-08-08")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()

    hp = T.HParams(cutoff=a.cutoff)
    ds = T.build_dataset(T.load_raw(a.data_dir), hp, "temporal")
    print(T.describe(ds))

    r1 = load_module("v1_recommender", ROOT / "engine_v1" / "recommender.py").Recommender(ROOT / "engine_v1" / "model_params")
    r2 = load_module("v2_recommender", ROOT / "engine_v2" / "recommender.py").Recommender(ROOT / "engine_v2" / "model_params")
    r3 = load_module("v3_recommender", ROOT / "engine_v3" / "recommender.py").Recommender(a.v3_dir)

    def v1(uid, exclude):
        vec = r1.user_vector_from_id(uid)
        if vec is None:
            return None
        return r1.recommend_from_vector(vec, exclude=exclude, top_k=10) or r1.popular_tracks(exclude=exclude, top_k=10)

    def v2(uid, exclude):
        prof = r2.profile_from_id(uid)
        if prof is None:
            return None
        return r2.recommend_from_profile(prof, exclude=exclude, top_k=10) or r2.popular_tracks(exclude=exclude, top_k=10)

    def v3(uid, exclude):
        prof = r3.profile_from_id(uid)
        if prof is None:
            return None
        return r3.recommend_from_profile(prof, exclude=exclude, top_k=10) or r3.popular_tracks(exclude=exclude, top_k=10)

    known = [u for u in ds.eval_targets if r1.user_vector_from_id(u) is not None
             and r2.profile_from_id(u) is not None and r3.profile_from_id(u) is not None]
    full_targets = ds.eval_targets
    ds.eval_targets = {u: full_targets[u] for u in known}
    print(f"eval users: {len(full_targets)} with history, {len(known)} known to all three engines, "
          f"{sum(len(v) for v in ds.eval_targets.values())} target tracks")

    results = {
        "popularity": T.evaluate_fn(ds, T.popularity_baseline(ds)),
        "v1 (in production)": T.evaluate_fn(ds, v1),
        "v2 (never deployed)": T.evaluate_fn(ds, v2),
        "v3": T.evaluate_fn(ds, v3),
    }
    cols = ["recall@10", "precision@10", "hit@10", "hit@1", "ndcg@10"]
    print(f"\n{'engine':22s} " + " ".join(f"{c:>13s}" for c in cols))
    for name, m in results.items():
        print(f"{name:22s} " + " ".join(f"{m[c]:13.4f}" for c in cols))
    if a.report:
        a.report.write_text(json.dumps({"users": len(known), "results": results}, indent=2))


if __name__ == "__main__":
    main()
