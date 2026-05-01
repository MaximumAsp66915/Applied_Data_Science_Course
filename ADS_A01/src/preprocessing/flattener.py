import pandas as pd
import json
import ast
import numpy as np

def flatten_and_clean(df_tracks, df_artists, df_users):
    t_df = df_tracks.copy()
    a_df = df_artists.copy()
    u_df = df_users.copy()
    
    def parse_and_flatten(val):
        if pd.isna(val): return np.nan
        if isinstance(val, str):
            val = val.strip()
            if not val or val.lower() == 'null' or val == '[null]': return np.nan
            
            # Try to parse stringified list
            parsed = None
            try: parsed = json.loads(val)
            except: pass
            
            if parsed is None:
                try: parsed = ast.literal_eval(val)
                except: pass
                
            if parsed is None:
                try: parsed = json.loads(val.replace("'", '"'))
                except: pass
            
            if isinstance(parsed, list):
                # Only flatten simple lists of strings/numbers, ignore if it contains dicts
                if all(not isinstance(item, dict) for item in parsed):
                    # Filter out any literal 'null' inside the list
                    clean_items = [str(item) for item in parsed if str(item).lower() != 'null' and item is not None]
                    if not clean_items:
                        return np.nan
                    return ", ".join(clean_items)
            
            if val.lower() == 'null' or val == '[null]':
                return np.nan
                
        return val

    # Target simple list columns to flatten
    target_cols_tracks = ['artist_names', 'sender_usernames', 'sender_chat_ids']
    for col in target_cols_tracks:
        if col in t_df.columns:
            t_df[col] = t_df[col].apply(parse_and_flatten)

    # Convert literal "null" strings to NaN everywhere else for robustness
    t_df.replace(to_replace=[r'^null$', r'^\[null\]$'], value=np.nan, regex=True, inplace=True)
    a_df.replace(to_replace=[r'^null$', r'^\[null\]$'], value=np.nan, regex=True, inplace=True)
    u_df.replace(to_replace=[r'^null$', r'^\[null\]$'], value=np.nan, regex=True, inplace=True)

    return t_df, a_df, u_df
