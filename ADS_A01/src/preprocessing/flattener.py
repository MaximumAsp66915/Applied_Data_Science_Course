import pandas as pd
import json
import ast
import numpy as np

def flatten_and_clean(df_tracks, df_artists, df_users):
    t_df = df_tracks.copy()
    a_df = df_artists.copy()
    u_df = df_users.copy()
    
    def parse_and_flatten(val, is_artist_dislikes=False):
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
                        
                        # Special rule for artist dislikes: ignore the reaction label
                        if is_artist_dislikes:
                            if uid:
                                clean_items.append(str(uid))
                            continue
                            
                        reaction = item.get('reaction', '')
                        if uid and reaction:
                            clean_items.append(f"{uid}:{reaction}")
                        elif uid: # if only uid is present, but it's meant to be a reaction mapping? Just use uid
                            clean_items.append(str(uid))
                        else:
                            # Just format the dict compactly without brackets
                            parts = [f"{k}={v}" for k,v in item.items() if not (is_artist_dislikes and k == 'reaction')]
                            clean_items.append("(" + ", ".join(parts) + ")")
                    else:
                        clean_items.append(str(item))
                        
                if not clean_items:
                    return np.nan
                return ", ".join(clean_items)
            elif isinstance(parsed, dict):
                # if the val parsed as a single dict, not a list of dicts
                uid = parsed.get('user_id', parsed.get('track_id', parsed.get('artist_id', '')))
                if is_artist_dislikes:
                    return str(uid) if uid else np.nan
                reaction = parsed.get('reaction', '')
                if uid and reaction:
                    return f"{uid}:{reaction}"
                elif uid:
                    return str(uid)
                else:
                    return "(" + ", ".join([f"{k}={v}" for k,v in parsed.items()]) + ")"
                
            if val.lower() == 'null' or val == '[null]':
                return np.nan
                
        return val

    # Target ALL columns that could contain stringified lists/JSON
    for col in t_df.columns:
        if t_df[col].astype(str).str.startswith('[').any() or t_df[col].astype(str).str.startswith('{').any():
            t_df[col] = t_df[col].apply(lambda x: parse_and_flatten(x, False))
            
    for col in a_df.columns:
        if a_df[col].astype(str).str.startswith('[').any() or a_df[col].astype(str).str.startswith('{').any():
            is_dislike = (col == 'dislikes')
            a_df[col] = a_df[col].apply(lambda x: parse_and_flatten(x, is_artist_dislikes=is_dislike))
            
    for col in u_df.columns:
        if u_df[col].astype(str).str.startswith('[').any() or u_df[col].astype(str).str.startswith('{').any():
            u_df[col] = u_df[col].apply(lambda x: parse_and_flatten(x, False))

    for df in [t_df, a_df, u_df]:
        df.replace(to_replace=[r'^null$', r'^\[null\]$'], value=np.nan, regex=True, inplace=True)

    return t_df, a_df, u_df
