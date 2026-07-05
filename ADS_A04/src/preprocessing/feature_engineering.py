# src/preprocessing/feature_engineering.py
import re
import pandas as pd
import numpy as np

def parse_reaction_value(cell):
    """Sums up numerical evaluations inside string reactions (e.g., '123:4, 56:-2')."""
    total = 0
    parts = str(cell).split(",")
    for p in parts:
        match = re.match(r"^\s*\d+\s*:\s*(-?\d+)\s*$", p.strip())
        if match:
            total += int(match.group(1))
    return total

def add_reactions_weighted_sum(df):
    df = df.copy()
    df["reactions_w_sum"] = df["reactions"].apply(parse_reaction_value) if "reactions" in df.columns else 0
    return df

def aggregate_track_features(df_tracks, df_artists, df_users):
    """Compresses tabular features by cross-referencing artists/users with relational tracks."""
    df_tracks = df_tracks.copy()
    artist_dict = {str(k): v for k, v in df_artists.set_index('artist_id').to_dict('index').items()} if 'artist_id' in df_artists.columns else {}
    user_dict = {str(k): v for k, v in df_users.set_index('user_id').to_dict('index').items()} if 'user_id' in df_users.columns else {}
    
    artist_cols = ['num_likes', 'num_dislikes', 'num_reactions']
    artist_agg, user_agg = [], []
    
    for _, row in df_tracks.iterrows():
        a_ids = [x.strip() for x in str(row.get('artist_ids', '')).split(',')] if pd.notna(row.get('artist_ids')) else []
        a_vals = {c: 0 for c in artist_cols}
        for a_id in a_ids:
            if a_id in artist_dict:
                for c in artist_cols: a_vals[c] += artist_dict[a_id].get(c, 0)
        artist_agg.append(a_vals)
        
    df_artist_agg = pd.DataFrame(artist_agg).rename(columns=lambda c: f"artists_total_{c[4:]}")
    df_tracks_new = pd.concat([df_tracks.reset_index(drop=True), df_artist_agg.reset_index(drop=True)], axis=1)
    return df_tracks_new