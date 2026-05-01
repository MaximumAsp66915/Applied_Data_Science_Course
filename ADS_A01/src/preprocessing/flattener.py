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
                # Flatten the list elements
                clean_items = []
                for item in parsed:
                    if str(item).lower() == 'null' or item is None:
                        continue
                        
                    # If it's a dict (like a reaction), simplify it to "ID: Reaction"
                    if isinstance(item, dict):
                        # Extract an ID if present
                        uid = item.get('user_id', item.get('track_id', item.get('artist_id', '')))
                        reaction = item.get('reaction', '')
                        if uid and reaction:
                            clean_items.append(f"{uid}:{reaction}")
                        else:
                            # Just format the dict compactly without brackets
                            parts = [f"{k}={v}" for k,v in item.items()]
                            clean_items.append("(" + ", ".join(parts) + ")")
                    else:
                        clean_items.append(str(item))
                        
                if not clean_items:
                    return np.nan
                return ", ".join(clean_items)
            
            if val.lower() == 'null' or val == '[null]':
                return np.nan
                
        return val

    # Target ALL columns that could contain stringified lists/JSON
    for df in [t_df, a_df, u_df]:
        for col in df.columns:
            # Try to identify stringified list columns roughly
            if df[col].astype(str).str.startswith('[').any():
                df[col] = df[col].apply(parse_and_flatten)
            
        # Convert literal "null" strings to NaN everywhere else for robustness
        df.replace(to_replace=[r'^null$', r'^\[null\]$'], value=np.nan, regex=True, inplace=True)

    return t_df, a_df, u_df
