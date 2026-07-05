# src/preprocessing/data_cleaners.py
import re
import ast
import json
import numpy as np
import pandas as pd

def flatten_and_clean(df_tracks, df_artists, df_users):
    """Parses text fields, flattens relational lists, and drops invalid objects."""
    t_df, a_df, u_df = df_tracks.copy(), df_artists.copy(), df_users.copy()
    
    def parse_and_flatten(val, is_artist_dislikes=False):
        if pd.isna(val): return np.nan
        if isinstance(val, str):
            val = val.strip()
            if not val or val.lower() == 'null' or val == '[null]': return np.nan
            
            parsed = None
            try: parsed = json.loads(val)
            except: pass
            try: 
                if parsed is None: parsed = ast.literal_eval(val)
            except: pass
            try:
                if parsed is None: parsed = json.loads(val.replace("'", '"'))
            except: pass
            
            if isinstance(parsed, list):
                clean_items = []
                for item in parsed:
                    if str(item).lower() == 'null' or item is None: continue
                    if isinstance(item, dict):
                        uid = item.get('user_id', item.get('track_id', item.get('artist_id', '')))
                        if is_artist_dislikes:
                            if uid: clean_items.append(str(uid))
                            continue
                        reaction = item.get('reaction', '')
                        if uid and reaction: clean_items.append(f"{uid}:{reaction}")
                        elif uid: clean_items.append(str(uid))
                    else:
                        clean_items.append(str(item))
                return ", ".join(clean_items) if clean_items else np.nan
        return val

    for col in t_df.columns:
        if t_df[col].astype(str).str.startswith('[').any() or t_df[col].astype(str).str.startswith('{').any():
            t_df[col] = t_df[col].apply(lambda x: parse_and_flatten(x, False))
    for col in a_df.columns:
        if a_df[col].astype(str).str.startswith('[').any() or a_df[col].astype(str).str.startswith('{').any():
            a_df[col] = a_df[col].apply(lambda x: parse_and_flatten(x, is_artist_dislikes=(col == 'dislikes')))
    
    return t_df, a_df, u_df


def simplify_all_ids(df_tracks, df_artists, df_users):
    """Remaps long text/hex hashes into predictable, sequentially isolated incremental IDs."""
    t_df, a_df, u_df = df_tracks.copy(), df_artists.copy(), df_users.copy()
    global_u, global_t, global_a = {}, {}, {}
    u_idx, t_idx, a_idx = 1, 1, 1

    for val in u_df['user_id'].dropna().astype(str).unique() if 'user_id' in u_df.columns else []:
        if val not in global_u: global_u[val] = u_idx; u_idx += 1
    for val in t_df['track_id'].dropna().astype(str).unique() if 'track_id' in t_df.columns else []:
        if val not in global_t: global_t[val] = t_idx; t_idx += 1

    if 'track_id' in t_df.columns:
        t_df['track_id'] = t_df['track_id'].astype(str).map(lambda x: global_t.get(x, x)).astype(int)
    if 'user_id' in u_df.columns:
        u_df['user_id'] = u_df['user_id'].astype(str).map(lambda x: global_u.get(x, x)).astype(int)
        
    return t_df, a_df, u_df


def normalize_texts(df_tracks, df_artists):
    """Applies case insensitivity and strips padding from textual features."""
    t_df, a_df = df_tracks.copy(), df_artists.copy()
    for col in ['track_name', 'artist_names']:
        if col in t_df.columns: t_df[col] = t_df[col].astype(str).str.strip().str.lower()
    if 'artist_name' in a_df.columns:
        a_df['artist_name'] = a_df['artist_name'].astype(str).str.strip().str.lower()
    return t_df, a_df