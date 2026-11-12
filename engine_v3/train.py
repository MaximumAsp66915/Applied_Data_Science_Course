"""engine_v3 training pipeline: raw CSV exports -> model_params/ (CPU only).

    python train.py --data-dir <dir with the 5 CSVs> --split full

Replaces the notebook workflow of engine_v2 (cleaning cells -> dedup ->
genre cleaning -> training cell) with one repeatable script. Needs the
packages in requirements-train.txt; the SERVER only needs requirements.txt
(inference is numpy-only, torch is never imported there).

Inputs (headers required -- columns are read by name):
    track_reactions.csv  artist_reactions.csv  reaction_types.csv
    artists.csv          tracks.csv
    (the exports of the matching Postgres tables, see notebooks/2.database-management.md)

What it learns (same two-stage design as v2, see README.md):
    stage 1  HybridArtistMF  user x artist, artist = id-embedding + genre projection,
                             weighted BPR + related-artist edge regulariser
    stage 2  TrackHybrid     user x track, track = id + artist + uploader embeddings
                             (so tracks nobody has reacted to yet still get a sensible
                             vector), BPR with optional dislike hard-negatives

Data changes vs the v2 notebook (all measured on the real export, see README.md):
    * artist_reactions are 100% bot-generated duplicates of track reactions. They are
      only used where NO track reaction covers that (user, artist) -- the v2 pipeline
      counted every first-artist reaction twice.
    * every artist credited on a track gets credit, not just the first one
      (2,891 tracks have 2+ artists).
    * a (user, track) pair counts once even if the user reacted with several emojis.
    * a user reacting to their own upload is dropped (their upload is already a signal).
    * tracks without any positive reaction yet are kept in the model's universe.

Evaluation splits (`--split`):
    full      train on everything, export (no evaluation)           <- the shipped model
    temporal  train on reactions before --cutoff, test on the ones after (out-of-time,
              the honest number)
    random    hold out ~15% of each user's positives (large, stable; used for tuning)
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

POSITIVE_THRESHOLD = 1.0  # reaction score strictly above this == a like (same as v2)
NEGATIVE_THRESHOLD = 0.0  # reaction score strictly below this == a dislike
INVISIBLE_CODES = {0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060, 0x3164}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================================
# Hyper-parameters
# ============================================================================
@dataclass
class HParams:
    seed: int = 43
    threads: int = 4
    cutoff: str = "2026-08-08"  # temporal split: train < cutoff <= test
    holdout_frac: float = 0.15  # random split

    # ---- artist model ----
    art_dim: int = 128
    art_epochs: int = 60
    art_bs: int = 512
    art_lr: float = 3e-3
    art_wd: float = 1e-5
    art_wtf: str = "log1p"  # how raw summed reaction scores become BPR weights: raw|log1p|sqrt
    upload_w: float = 5.0  # same constant as v2
    syn_w: float = 0.2  # weight of synthetic related-artist interactions (0 = off)
    edge_lambda: float = 0.05  # related-artist embedding-distance regulariser (0 = off)
    use_genre: bool = True
    min_genre_count: int = 5
    zero_cold_id: bool = True  # artists with no interactions: use genre part only

    # ---- track model ----
    trk_dim: int = 64
    trk_epochs: int = 60
    trk_bs: int = 512
    trk_lr: float = 3e-3
    trk_wd: float = 1e-5
    trk_score_w: bool = False  # weight each positive by reaction score / 4
    trk_use_artist: bool = True
    trk_use_uploader: bool = True
    trk_uploads_as_pos: bool = True
    hard_neg_p: float = 0.0  # chance a negative sample is one of the user's own dislikes (tested 0/0.2/0.5: 0 was best)

    # ---- serving defaults written into ensemble_config.json ----
    srv_n_artists: int = 120
    srv_tpa: int = 30
    srv_bias_w: float = 0.25
    srv_pop_w: float = 0.5  # chosen by worst-case (maximin) over a random and an out-of-time split


def apply_overrides(hp: HParams, pairs: list[str]) -> HParams:
    types = {f.name: f.type for f in fields(HParams)}
    for kv in pairs or []:
        k, _, v = kv.partition("=")
        if k not in types:
            raise SystemExit(f"unknown hyper-parameter: {k}")
        try:
            val = json.loads(v)
        except json.JSONDecodeError:
            val = v
        setattr(hp, k, val)
    return hp


# ============================================================================
# Raw data -> clean tables
# ============================================================================
def normalize_name(name) -> str:
    """Same artist-name normalisation as the v2 notebook (NFKD, no diacritics /
    invisible chars, lower-case, collapsed whitespace, trimmed punctuation)."""
    if pd.isna(name):
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c for c in s if ord(c) not in INVISIBLE_CODES and unicodedata.category(c) != "Cf")
    s = " ".join(s.lower().split())
    return s.strip(".,-;:!?'\" ")


def parse_ids(value) -> list[int]:
    """'{1,2}' / '1' / NaN -> [1, 2] / [1] / []"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    out = []
    for part in str(value).strip().strip("{}").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


def load_raw(data_dir: Path) -> dict[str, pd.DataFrame]:
    d = Path(data_dir)
    need = {
        "track_reactions.csv": ["track_id", "user_id", "reacted_at", "reaction_id"],
        "artist_reactions.csv": ["artist_id", "user_id", "reacted_at", "reaction_id"],
        "reaction_types.csv": ["id", "score"],
        "artists.csv": ["id", "name", "metadata"],
        "tracks.csv": ["id", "artists_id", "uploaded_by", "created_at"],
    }
    out = {}
    for fname, cols in need.items():
        df = pd.read_csv(d / fname, usecols=lambda c, cols=cols: c in cols)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise SystemExit(f"{fname}: missing columns {missing} -- the CSVs must keep their header row")
        out[fname.removesuffix(".csv")] = df
    return out


def clean_genres(raw_counts: Counter) -> dict[str, str]:
    """raw Last.fm genre string -> canonical label. Same idea as the v2 notebook:
    normalise, then merge near-duplicates (token-sort ratio >= 90 AND at least one
    shared word), the most frequent spelling becomes the canonical one."""
    from rapidfuzz import fuzz, process

    def norm(g: str) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", g.strip().lower()).split())

    freq: Counter = Counter()
    for raw, c in raw_counts.items():
        n = norm(raw)
        if n:
            freq[n] += c
    names = sorted(freq, key=lambda n: (-freq[n], n))
    if not names:
        return {}
    sim = process.cdist(names, names, scorer=fuzz.token_sort_ratio, score_cutoff=90, workers=-1)
    words = [set(n.split()) for n in names]
    head: dict[str, str] = {}
    for i, n in enumerate(names):
        if n in head:
            continue
        head[n] = n
        for j in np.nonzero(sim[i] >= 90)[0]:
            j = int(j)
            if j > i and names[j] not in head and words[i] & words[j]:
                head[names[j]] = n
    return {raw: head[norm(raw)] for raw in raw_counts if norm(raw)}


# ============================================================================
# Dataset (one object for artist side, track side and evaluation)
# ============================================================================
class Dataset:
    pass


def build_dataset(raw: dict[str, pd.DataFrame], hp: HParams, split: str) -> Dataset:
    assert split in ("full", "temporal", "random")
    rng = np.random.default_rng(hp.seed)
    ds = Dataset()
    ds.split = split
    cutoff = pd.Timestamp(hp.cutoff, tz="UTC")

    tr, ar, rt = raw["track_reactions"].copy(), raw["artist_reactions"].copy(), raw["reaction_types"]
    artists, tracks = raw["artists"].copy(), raw["tracks"].copy()
    score_of = dict(zip(rt["id"], rt["score"]))
    for df in (tr, ar):
        df["score"] = df["reaction_id"].map(score_of).fillna(0.0)
        df["t"] = pd.to_datetime(df["reacted_at"], utc=True, errors="coerce").fillna(pd.Timestamp.min.tz_localize("UTC"))
    tracks["c"] = pd.to_datetime(tracks["created_at"], utc=True, errors="coerce").fillna(pd.Timestamp.min.tz_localize("UTC"))

    # ---- artist de-duplication (same rule as v2: smallest id of a normalised name) ----
    artists["nn"] = artists["name"].map(normalize_name)
    grp_min = artists.groupby("nn")["id"].transform("min")
    artists["canon"] = np.where(artists["nn"] == "", artists["id"], grp_min)
    id2can = {int(a): int(c) for a, c in zip(artists["id"], artists["canon"])}
    ds.artist_alias = {a: c for a, c in id2can.items() if a != c}
    canon_artists = set(id2can.values())

    # ---- tracks: credited artists (canonical, order kept, de-duplicated) + uploaders ----
    def canon_list(v):
        seen, out = set(), []
        for a in parse_ids(v):
            c = id2can.get(a)
            if c is not None and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    tracks["aids"] = tracks["artists_id"].map(canon_list)
    tracks["ups"] = tracks["uploaded_by"].map(parse_ids)
    track_aids = {int(t): a for t, a in zip(tracks["id"], tracks["aids"])}
    track_ups = {int(t): u for t, u in zip(tracks["id"], tracks["ups"])}
    track_created = {int(t): c for t, c in zip(tracks["id"], tracks["c"])}
    all_track_ids = np.array(sorted(track_aids), dtype=np.int64)

    # ---- last.fm metadata: genres + related artists, merged over duplicate ids ----
    genres_of: dict[int, set] = defaultdict(set)
    related_names: dict[int, set] = defaultdict(set)
    for aid, meta in zip(artists["id"], artists["metadata"]):
        if pd.isna(meta) or not str(meta).strip():
            continue
        try:
            d = json.loads(str(meta))
        except json.JSONDecodeError:
            continue
        c = id2can[int(aid)]
        genres_of[c].update(g for g in d.get("genres", []) if isinstance(g, str))
        related_names[c].update(r for r in d.get("related_artists", []) if isinstance(r, str))
    name_to_canon = {}
    for aid, nn in zip(artists["id"], artists["nn"]):
        if nn:
            name_to_canon.setdefault(nn, id2can[int(aid)])
    links = set()
    for a, names in related_names.items():
        for n in names:
            r = name_to_canon.get(normalize_name(n))
            if r is not None and r != a:
                links.add((a, r))

    # ---- interaction tables (positives / negatives / uploads), self-reactions removed ----
    upl = pd.DataFrame([(u, t) for t, us in track_ups.items() for u in us], columns=["user_id", "track_id"])
    upl["c"] = upl["track_id"].map(track_created)
    up_keys = pd.MultiIndex.from_frame(upl[["user_id", "track_id"]])
    tr = tr[tr["track_id"].isin(track_aids)]
    self_mask = pd.MultiIndex.from_frame(tr[["user_id", "track_id"]]).isin(up_keys)
    ds.n_self_reactions = int(self_mask.sum())
    tr = tr[~self_mask]
    pos = tr[tr["score"] > POSITIVE_THRESHOLD]
    pp = pos.groupby(["user_id", "track_id"]).agg(s=("score", "max"), t=("t", "min")).reset_index()
    neg = tr[tr["score"] < NEGATIVE_THRESHOLD].groupby(["user_id", "track_id"]).agg(t=("t", "min")).reset_index()
    neg = neg[~pd.MultiIndex.from_frame(neg[["user_id", "track_id"]]).isin(pd.MultiIndex.from_frame(pp[["user_id", "track_id"]]))]

    # which (user, artist) pairs are already explained by a track reaction (all time)?
    ta = pd.DataFrame([(t, a) for t, al in track_aids.items() for a in al], columns=["track_id", "artist"])
    covered = pp.merge(ta, on="track_id")[["user_id", "artist"]].drop_duplicates()
    covered_keys = pd.MultiIndex.from_frame(covered)
    ar = ar.assign(artist=ar["artist_id"].map(id2can))
    ar = ar[(ar["score"] > POSITIVE_THRESHOLD) & ar["artist"].notna()].copy()
    ar["artist"] = ar["artist"].astype(np.int64)
    # ...and a user reacting to their own upload also makes the bot log an artist reaction;
    # their upload already carries that signal, so those are dropped too.
    uploaded = upl.merge(ta, on="track_id")[["user_id", "artist"]].drop_duplicates()
    skip_keys = covered_keys.union(pd.MultiIndex.from_frame(uploaded))
    ar_extra_all = ar[~pd.MultiIndex.from_frame(ar[["user_id", "artist"]]).isin(skip_keys)]
    ds.n_artist_reactions_total = int(len(raw["artist_reactions"]))
    ds.n_artist_reactions_used = int(len(ar_extra_all))

    # ---- the split ----
    test_pp = pp.iloc[0:0]
    if split == "full":
        tr_pp, tr_neg, tr_up, ar_extra = pp, neg, upl, ar_extra_all
        universe = all_track_ids
    elif split == "temporal":
        tr_pp, test_pp = pp[pp["t"] < cutoff], pp[pp["t"] >= cutoff]
        tr_neg, tr_up = neg[neg["t"] < cutoff], upl[upl["c"] < cutoff]
        ar_extra = ar_extra_all[ar_extra_all["t"] < cutoff]
        universe = np.array(sorted(t for t, c in track_created.items() if c < cutoff), dtype=np.int64)
    else:
        n_u = pp.groupby("user_id")["track_id"].transform("size")
        rnd = pd.Series(rng.random(len(pp)), index=pp.index)
        rank = rnd.groupby(pp["user_id"]).rank(method="first")
        k_u = np.where(n_u >= 6, np.maximum(1, np.round(n_u * hp.holdout_frac)), 0)
        held = (rank.values <= k_u)
        tr_pp, test_pp = pp[~held], pp[held]
        tr_neg, tr_up, ar_extra = neg, upl, ar_extra_all
        universe = all_track_ids
    ds.universe = universe
    ds.n_train_pairs, ds.n_test_pairs = len(tr_pp), len(test_pp)
    uni_set = set(int(t) for t in universe)
    ds.outside_pool = set(int(t) for t in all_track_ids) - uni_set

    # ---- artist side: weighted (user, artist) pairs ----
    def sum_by(df, key_cols, w_col):
        return df.groupby(key_cols)[w_col].sum()

    parts = []
    m = tr_pp.merge(ta, on="track_id")
    parts.append(sum_by(m, ["user_id", "artist"], "s"))
    if len(tr_up):
        mu = tr_up.merge(ta, on="track_id").assign(w=hp.upload_w)
        parts.append(sum_by(mu, ["user_id", "artist"], "w"))
    if len(ar_extra):
        parts.append(sum_by(ar_extra, ["user_id", "artist"], "score"))
    pairs = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
    pairs.columns = ["user_id", "artist", "w"]
    pairs = pairs[pairs["w"] > 0]
    if hp.art_wtf == "log1p":
        pairs["w"] = np.log1p(pairs["w"])
    elif hp.art_wtf == "sqrt":
        pairs["w"] = np.sqrt(pairs["w"])

    art_ids = np.array(sorted(set(pairs["artist"]) | {a for al in track_aids.values() for a in al}), dtype=np.int64)
    ua_users = np.array(sorted(set(pairs["user_id"])), dtype=np.int64)
    U, A = len(ua_users), len(art_ids)
    rows = np.searchsorted(ua_users, pairs["user_id"].values)
    cols = np.searchsorted(art_ids, pairs["artist"].values)
    w = pairs["w"].values.astype(np.float32)
    Ub = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(U, A))
    cold = np.asarray(Ub.sum(axis=0)).ravel() == 0

    a_pos = {int(a): i for i, a in enumerate(art_ids)}
    lk = [(a_pos[a], a_pos[b]) for a, b in links if a in a_pos and b in a_pos]
    edges = np.array(lk, dtype=np.int64).T if lk else np.zeros((2, 0), np.int64)
    n_syn = 0
    if hp.syn_w > 0 and len(lk):
        R = sp.csr_matrix((np.ones(len(lk), np.float32), (edges[0], edges[1])), shape=(A, A))
        S = (Ub @ R).astype(bool).astype(np.float32)
        S = (S - S.multiply(Ub)).tocoo()
        keep = S.data > 0
        rows = np.concatenate([rows, S.row[keep]])
        cols = np.concatenate([cols, S.col[keep]])
        w = np.concatenate([w, np.full(int(keep.sum()), hp.syn_w, np.float32)])
        n_syn = int(keep.sum())

    # genre matrix over canonical artists
    G = np.zeros((A, 0), np.float32)
    if hp.use_genre:
        counts = Counter(g for a in art_ids for g in genres_of.get(int(a), ()))
        mapping = clean_genres(counts)
        per_art = {int(a): {mapping[g] for g in genres_of.get(int(a), ()) if g in mapping} for a in art_ids}
        gcount = Counter(g for gs in per_art.values() for g in gs)
        kept = sorted(g for g, c in gcount.items() if c >= hp.min_genre_count)
        gidx = {g: i for i, g in enumerate(kept)}
        G = np.zeros((A, len(kept)), np.float32)
        for a, gs in per_art.items():
            for g in gs:
                if g in gidx:
                    G[a_pos[a], gidx[g]] = 1.0
        ds.n_raw_genres, ds.n_genres = len(counts), len(kept)

    ds.ua_users, ds.art_ids = ua_users, art_ids
    ds.ua_rows, ds.ua_cols, ds.ua_w = rows.astype(np.int64), cols.astype(np.int64), w
    ds.n_real_pairs, ds.n_syn_pairs = len(pairs), n_syn
    ds.edges, ds.G, ds.cold = edges, G, cold
    ds.n_users_art, ds.n_art = U, A

    # ---- track side ----
    pos_users = set(tr_pp["user_id"])
    tpos = tr_pp[["user_id", "track_id", "s"]].copy()
    if hp.trk_uploads_as_pos and len(tr_up):
        up_pos = tr_up[["user_id", "track_id"]].assign(s=hp.upload_w)
        tpos = pd.concat([tpos, up_pos]).groupby(["user_id", "track_id"], as_index=False)["s"].max()
    tpos = tpos[tpos["track_id"].isin(uni_set)]
    trk_users = np.array(sorted(set(tpos["user_id"])), dtype=np.int64)
    T = len(universe)
    ds.trk_users, ds.n_users_trk, ds.n_items = trk_users, len(trk_users), T
    ds.tp_rows = np.searchsorted(trk_users, tpos["user_id"].values).astype(np.int64)
    ds.tp_cols = np.searchsorted(universe, tpos["track_id"].values).astype(np.int64)
    ds.tp_w = (tpos["s"].values / 4.0).astype(np.float32) if hp.trk_score_w else np.ones(len(tpos), np.float32)

    n_neg = tr_neg[tr_neg["track_id"].isin(uni_set) & tr_neg["user_id"].isin(set(trk_users.tolist()))]
    nr = np.searchsorted(trk_users, n_neg["user_id"].values)
    nc = np.searchsorted(universe, n_neg["track_id"].values)
    order = np.argsort(nr, kind="stable")
    ds.neg_idx = nc[order].astype(np.int64)
    ds.neg_ptr = np.concatenate([[0], np.cumsum(np.bincount(nr, minlength=len(trk_users)))]).astype(np.int64)

    dummy_a, ups_all = A, sorted({u for us in track_ups.values() for u in us})
    up_pos_map = {u: i for i, u in enumerate(ups_all)}
    ds.n_uploaders = len(ups_all)
    ds.t_art = np.array([a_pos.get(track_aids[int(t)][0], dummy_a) if track_aids[int(t)] else dummy_a for t in universe], np.int64)
    ds.t_up = np.array([up_pos_map[track_ups[int(t)][0]] if track_ups[int(t)] else len(ups_all) for t in universe], np.int64)
    pop = tr_pp[tr_pp["track_id"].isin(uni_set)].groupby("track_id")["user_id"].nunique()
    ds.pop = np.zeros(T, np.float32)
    ds.pop[np.searchsorted(universe, pop.index.values)] = pop.values.astype(np.float32)

    # ---- export-side maps ----
    ds.track_to_artist = {int(t): int(al[0]) for t, al in track_aids.items() if al and int(t) in uni_set}
    ds.track_artists = {int(t): [int(a) for a in al] for t, al in track_aids.items() if al and int(t) in uni_set}

    # ---- evaluation material ----
    seen: dict[int, set] = defaultdict(set)
    for df in (tr_pp[["user_id", "track_id"]], tr_neg[["user_id", "track_id"]], tr_up[["user_id", "track_id"]]):
        for u, t in zip(df["user_id"].values, df["track_id"].values):
            seen[int(u)].add(int(t))
    targets: dict[int, set] = defaultdict(set)
    for u, t in zip(test_pp["user_id"].values, test_pp["track_id"].values):
        u, t = int(u), int(t)
        if t in uni_set and t not in seen[u]:
            targets[u].add(t)
    known_users = set(ua_users.tolist())
    ds.eval_seen, ds.eval_targets = seen, {u: ts for u, ts in targets.items() if ts and u in known_users}
    return ds


def describe(ds: Dataset) -> str:
    return (
        f"split={ds.split} | artist model: {ds.n_users_art} users x {ds.n_art} artists, {ds.n_real_pairs} real + "
        f"{ds.n_syn_pairs} synthetic pairs, {ds.edges.shape[1]} related edges, {ds.G.shape[1]} genres, "
        f"{int(ds.cold.sum())} cold artists | track model: {ds.n_users_trk} users x {ds.n_items} tracks, "
        f"{len(ds.tp_rows)} positives, {len(ds.neg_idx)} dislikes | train pairs {ds.n_train_pairs}, test pairs {ds.n_test_pairs}, "
        f"eval users {len(ds.eval_targets)}, eval targets {sum(len(v) for v in ds.eval_targets.values())} | "
        f"self-reactions dropped {ds.n_self_reactions}, artist_reactions used {ds.n_artist_reactions_used}/{ds.n_artist_reactions_total}"
    )


# ============================================================================
# Models
# ============================================================================
def train_artist(ds: Dataset, hp: HParams):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    torch.manual_seed(hp.seed)
    U, A = ds.n_users_art, ds.n_art
    G = torch.from_numpy(ds.G) if (hp.use_genre and ds.G.shape[1]) else None

    class HybridArtistMF(nn.Module):
        def __init__(self):
            super().__init__()
            self.user_emb = nn.Embedding(U, hp.art_dim)
            self.id_emb = nn.Embedding(A, hp.art_dim)
            self.proj = nn.Linear(G.shape[1], hp.art_dim, bias=False) if G is not None else None
            self.bias = nn.Embedding(A, 1)
            nn.init.xavier_uniform_(self.user_emb.weight)
            nn.init.xavier_uniform_(self.id_emb.weight)
            nn.init.zeros_(self.bias.weight)

        def art(self, a):
            e = self.id_emb(a)
            return e + self.proj(G[a]) if self.proj is not None else e

    model = HybridArtistMF()
    opt = torch.optim.Adam(model.parameters(), lr=hp.art_lr, weight_decay=hp.art_wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=hp.art_epochs, eta_min=hp.art_lr / 100)
    rows, cols, w = map(torch.from_numpy, (ds.ua_rows, ds.ua_cols, ds.ua_w))
    N = len(rows)
    known = torch.zeros(U, A, dtype=torch.bool)
    known[rows, cols] = True
    edges = torch.from_numpy(ds.edges) if (hp.edge_lambda > 0 and ds.edges.shape[1]) else None
    t0 = time.time()
    for ep in range(1, hp.art_epochs + 1):
        perm = torch.randperm(N)
        negs = torch.randint(0, A, (N,))
        for _ in range(3):  # re-draw negatives that are known positives
            bad = known[rows[perm], negs]
            if not bad.any():
                break
            negs[bad] = torch.randint(0, A, (int(bad.sum()),))
        tot = 0.0
        for s in range(0, N, hp.art_bs):
            idx = perm[s : s + hp.art_bs]
            u, p, n, ww = rows[idx], cols[idx], negs[s : s + hp.art_bs], w[idx]
            ue = model.user_emb(u)
            ps = (ue * model.art(p)).sum(-1) + model.bias(p).squeeze(-1)
            ns = (ue * model.art(n)).sum(-1) + model.bias(n).squeeze(-1)
            loss = (ww * F.softplus(-(ps - ns))).mean()
            if edges is not None:
                ei = torch.randint(0, edges.shape[1], (min(hp.art_bs, edges.shape[1]),))
                loss = loss + hp.edge_lambda * ((model.art(edges[0, ei]) - model.art(edges[1, ei])) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item()
        sched.step()
        if ep % 10 == 0 or ep == hp.art_epochs:
            log(f"  artist epoch {ep:3d}/{hp.art_epochs}  loss={tot / math.ceil(N / hp.art_bs):.4f}  ({time.time() - t0:.0f}s)")
    with torch.no_grad():
        id_emb = model.id_emb.weight.clone()
        if hp.zero_cold_id:
            id_emb[torch.from_numpy(ds.cold)] = 0.0
        art_emb = id_emb + (model.proj(G) if model.proj is not None else 0.0)
        bias = model.bias.weight.squeeze(-1).clone()
        if hp.zero_cold_id:
            bias[torch.from_numpy(ds.cold)] = 0.0
    return {
        "user_emb": model.user_emb.weight.detach().numpy().astype(np.float32),
        "art_emb": art_emb.numpy().astype(np.float32),
        "art_bias": bias.numpy().astype(np.float32),
    }


def train_track(ds: Dataset, hp: HParams):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    torch.manual_seed(hp.seed + 1)
    U, T, A = ds.n_users_trk, ds.n_items, ds.n_art
    t_art, t_up = torch.from_numpy(ds.t_art), torch.from_numpy(ds.t_up)

    class TrackHybrid(nn.Module):
        def __init__(self):
            super().__init__()
            self.user_emb = nn.Embedding(U, hp.trk_dim)
            self.id_emb = nn.Embedding(T, hp.trk_dim)
            self.art_emb = nn.Embedding(A + 1, hp.trk_dim) if hp.trk_use_artist else None
            self.up_emb = nn.Embedding(ds.n_uploaders + 1, hp.trk_dim) if hp.trk_use_uploader else None
            nn.init.xavier_uniform_(self.user_emb.weight)
            nn.init.normal_(self.id_emb.weight, std=0.01)
            for e in (self.art_emb, self.up_emb):
                if e is not None:
                    nn.init.normal_(e.weight, std=0.05)

        def items(self, idx):
            e = self.id_emb(idx)
            if self.art_emb is not None:
                e = e + self.art_emb(t_art[idx])
            if self.up_emb is not None:
                e = e + self.up_emb(t_up[idx])
            return e

    model = TrackHybrid()
    opt = torch.optim.Adam(model.parameters(), lr=hp.trk_lr, weight_decay=hp.trk_wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=hp.trk_epochs, eta_min=hp.trk_lr / 100)
    rows, cols, w = map(torch.from_numpy, (ds.tp_rows, ds.tp_cols, ds.tp_w))
    N = len(rows)
    known = torch.zeros(U, T, dtype=torch.bool)
    known[rows, cols] = True
    neg_idx, neg_ptr = torch.from_numpy(ds.neg_idx), torch.from_numpy(ds.neg_ptr)
    neg_cnt = neg_ptr[1:] - neg_ptr[:-1]
    use_hard = hp.hard_neg_p > 0 and len(neg_idx) > 0
    t0 = time.time()
    for ep in range(1, hp.trk_epochs + 1):
        perm = torch.randperm(N)
        negs = torch.randint(0, T, (N,))
        for _ in range(3):
            bad = known[rows[perm], negs]
            if not bad.any():
                break
            negs[bad] = torch.randint(0, T, (int(bad.sum()),))
        tot = 0.0
        for s in range(0, N, hp.trk_bs):
            idx = perm[s : s + hp.trk_bs]
            u, p, n, ww = rows[idx], cols[idx], negs[s : s + hp.trk_bs], w[idx]
            if use_hard:
                cnt = neg_cnt[u]
                take = (cnt > 0) & (torch.rand(len(u)) < hp.hard_neg_p)
                pick = (neg_ptr[u] + (torch.rand(len(u)) * cnt).long().clamp(max=(cnt - 1).clamp(min=0))).clamp(max=len(neg_idx) - 1)
                n = torch.where(take, neg_idx[pick], n)
            ue = model.user_emb(u)
            diff = (ue * model.items(p)).sum(-1) - (ue * model.items(n)).sum(-1)
            loss = (ww * F.softplus(-diff)).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item()
        sched.step()
        if ep % 10 == 0 or ep == hp.trk_epochs:
            log(f"  track  epoch {ep:3d}/{hp.trk_epochs}  loss={tot / math.ceil(N / hp.trk_bs):.4f}  ({time.time() - t0:.0f}s)")
    with torch.no_grad():
        items = model.items(torch.arange(T)).numpy().astype(np.float32)
    return {"user_emb": model.user_emb.weight.detach().numpy().astype(np.float32), "item_emb": items}


# ============================================================================
# Export (the exact model_params/ layout recommender.py loads)
# ============================================================================
def _encoder(ids):
    from sklearn.preprocessing import LabelEncoder

    le = LabelEncoder()
    le.classes_ = np.asarray(ids, dtype=np.int64)
    return le


def _dump(obj, path: Path):
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=4)


def export_params(out_dir: Path, ds: Dataset, art: dict, trk: dict, hp: HParams, extra: dict | None = None) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.iterdir():  # never leave files of an older export around
        if stale.is_file():
            stale.unlink()
    _dump(_encoder(ds.ua_users), out / "user_enc_artist.pkl")
    _dump(_encoder(ds.art_ids), out / "artist_enc.pkl")
    _dump(_encoder(ds.trk_users), out / "track_user_enc.pkl")
    _dump(_encoder(ds.universe), out / "track_item_enc.pkl")
    _dump(ds.track_to_artist, out / "track_to_artist.pkl")
    _dump(ds.track_artists, out / "track_artists.pkl")
    _dump({int(t): i for i, t in enumerate(ds.universe)}, out / "track_id_to_idx.pkl")
    _dump({int(a): int(c) for a, c in ds.artist_alias.items()}, out / "artist_alias.pkl")
    np.save(out / "artist_user_embeddings.npy", art["user_emb"])
    np.save(out / "artist_artist_embeddings.npy", art["art_emb"])
    np.save(out / "artist_bias.npy", art["art_bias"])
    np.save(out / "track_user_embeddings.npy", trk["user_emb"])
    np.save(out / "track_item_embeddings.npy", trk["item_emb"])
    np.save(out / "track_pop.npy", ds.pop)
    cfg = {
        "model_version": "v3",
        "artist_embedding_dim": hp.art_dim,
        "track_embedding_dim": hp.trk_dim,
        "n_users_artist": int(ds.n_users_art),
        "n_artists": int(ds.n_art),
        "n_users_track": int(ds.n_users_trk),
        "n_tracks": int(ds.n_items),
        "genre_dim": int(ds.G.shape[1]),
        "n_artists_candidates": hp.srv_n_artists,
        "tracks_per_artist_candidate": hp.srv_tpa,
        "top_k_final": 10,
        "artist_bias_weight": hp.srv_bias_w,
        "pop_weight": hp.srv_pop_w,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hyperparameters": asdict(hp),
    }
    cfg.update(extra or {})
    with open(out / "ensemble_config.json", "w") as f:
        json.dump(cfg, f, indent=2)


# ============================================================================
# Evaluation (always through the real Recommender, i.e. exactly what is served)
# ============================================================================
def evaluate_fn(ds: Dataset, recommend, top_k: int = 10) -> dict:
    """`recommend(uid, exclude) -> list[int] | None` (None = engine does not know the user)."""
    rec_, prec_, hit10, hit1, ndcg = [], [], [], [], []
    skipped = 0
    for uid, targets in ds.eval_targets.items():
        exclude = ds.eval_seen.get(uid, set()) | ds.outside_pool
        picks = recommend(uid, exclude)
        if picks is None:
            skipped += 1
            continue
        hits = [p in targets for p in picks[:top_k]]
        n = sum(hits)
        rec_.append(n / len(targets))
        prec_.append(n / top_k)
        hit10.append(1.0 if n else 0.0)
        hit1.append(1.0 if hits and hits[0] else 0.0)
        dcg = sum(1.0 / math.log2(i + 2) for i, h in enumerate(hits) if h)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(targets), top_k)))
        ndcg.append(dcg / idcg)
    f = lambda x: round(float(np.mean(x)), 4) if x else 0.0
    return {"users": len(rec_), "skipped_unknown_users": skipped, "recall@10": f(rec_), "precision@10": f(prec_),
            "hit@10": f(hit10), "hit@1": f(hit1), "ndcg@10": f(ndcg)}


def popularity_baseline(ds: Dataset):
    ranked = [int(ds.universe[i]) for i in np.argsort(-ds.pop, kind="stable")]

    def fn(uid, exclude):
        return [t for t in ranked if t not in exclude][:10]

    return fn


def v3_fn(rec, n_artists=None, tpa=None, bias_w=None, pop_w=None):
    def fn(uid, exclude):
        prof = rec.profile_from_id(uid)
        if prof is None:
            return None
        picks = rec.recommend_from_profile(prof, exclude=exclude, top_k=10, n_artists=n_artists,
                                           tracks_per_artist=tpa, bias_weight=bias_w, pop_weight=pop_w)
        return picks or rec.popular_tracks(exclude=exclude, top_k=10)

    return fn


def tune_serving(rec, ds: Dataset, hp: HParams) -> dict:
    """Coordinate search over the serving knobs on the evaluation users (two passes)."""
    best = dict(n_artists=hp.srv_n_artists, tpa=hp.srv_tpa, bias_w=hp.srv_bias_w, pop_w=hp.srv_pop_w)
    score = lambda cfg: evaluate_fn(ds, v3_fn(rec, **cfg))
    cur = score(best)
    log(f"  serving start {best} -> ndcg@10={cur['ndcg@10']} recall@10={cur['recall@10']}")
    grids = (("n_artists", [30, 50, 80, 120, 200, 300]), ("tpa", [10, 20, 30, 50, 100]),
             ("bias_w", [0.0, 0.25, 0.5, 1.0]), ("pop_w", [0.0, 0.1, 0.3, 0.6, 1.0]))
    for pass_no in (1, 2):
        for key, grid in grids if pass_no == 1 else grids[:2]:
            for v in grid:
                cand = dict(best, **{key: v})
                if cand == best:
                    continue
                m = score(cand)
                if m["ndcg@10"] > cur["ndcg@10"] + 1e-9:
                    best, cur = cand, m
            log(f"  serving pass {pass_no} after {key}: {best} -> ndcg@10={cur['ndcg@10']} recall@10={cur['recall@10']}")
    return {"best": best, "metrics": cur}


# ============================================================================
# CLI
# ============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--split", choices=["full", "temporal", "random"], default="full")
    ap.add_argument("--out-dir", type=Path, default=HERE / "model_params")
    ap.add_argument("--report", type=Path, help="write a JSON report here")
    ap.add_argument("--tune-serving", action="store_true", help="coordinate-search the serving knobs (not for --split full)")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE", help="override hyper-parameters")
    args = ap.parse_args()

    hp = apply_overrides(HParams(), args.set)
    import torch

    torch.set_num_threads(hp.threads)
    np.random.seed(hp.seed)

    log(f"loading {args.data_dir}")
    raw = load_raw(args.data_dir)
    ds = build_dataset(raw, hp, args.split)
    log(describe(ds))
    t0 = time.time()
    log("training artist model")
    art = train_artist(ds, hp)
    log("training track model")
    trk = train_track(ds, hp)
    log(f"training done in {time.time() - t0:.0f}s")

    report: dict = {"hyperparameters": asdict(hp), "split": args.split, "dataset": describe(ds)}
    export_params(args.out_dir, ds, art, trk, hp)
    from recommender import Recommender

    rec = Recommender(args.out_dir)
    # exported artifacts must agree with each other -- fail loudly, not at serving time
    assert len(rec.track_item_enc.classes_) == len(rec.track_id_to_idx) == rec.track_item_emb.shape[0] == len(rec.track_pop)
    assert rec.artist_artist_emb.shape[0] == len(rec.artist_enc.classes_) == len(rec.artist_bias)
    assert rec.artist_user_emb.shape[0] == len(rec.user_enc_artist.classes_)
    assert all(np.isfinite(a).all() for a in (rec.artist_user_emb, rec.artist_artist_emb, rec.track_user_emb, rec.track_item_emb))

    if args.split != "full":
        report["popularity"] = evaluate_fn(ds, popularity_baseline(ds))
        report["v3_default_serving"] = evaluate_fn(ds, v3_fn(rec))
        log(f"popularity   : {report['popularity']}")
        log(f"v3 (default) : {report['v3_default_serving']}")
        if args.tune_serving:
            tuned = tune_serving(rec, ds, hp)
            report["serving_tuned"] = tuned
    if args.report:
        args.report.write_text(json.dumps(report, indent=2))
    log("done")


if __name__ == "__main__":
    main()
