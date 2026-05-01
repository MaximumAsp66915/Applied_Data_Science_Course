import pandas as pd
import json
import ast

def simplify_all_ids(df_tracks, df_artists, df_users):
    t_df = df_tracks.copy()
    a_df = df_artists.copy()
    u_df = df_users.copy()
    
    global_u, global_t, global_a = {}, {}, {}
    u_idx, t_idx, a_idx = 1, 1, 1
    
    if 'user_id' in u_df.columns:
        for val in u_df['user_id'].dropna().astype(str).unique():
            if val not in global_u:
                global_u[val] = u_idx
                u_idx += 1
                
    if 'track_id' in t_df.columns:
        for val in t_df['track_id'].dropna().astype(str).unique():
            if val not in global_t:
                global_t[val] = t_idx
                t_idx += 1
                
    if 'artist_id' in a_df.columns:
        for val in a_df['artist_id'].dropna().astype(str).unique():
            if val not in global_a:
                global_a[val] = a_idx
                a_idx += 1

    def get_u_id(old_val):
        nonlocal u_idx
        v = str(old_val)
        if v not in global_u:
            global_u[v] = u_idx
            u_idx += 1
        return global_u[v]

    def get_t_id(old_val):
        nonlocal t_idx
        v = str(old_val)
        if v not in global_t:
            global_t[v] = t_idx
            t_idx += 1
        return global_t[v]

    def get_a_id(old_val):
        nonlocal a_idx
        v = str(old_val)
        if v not in global_a:
            global_a[v] = a_idx
            a_idx += 1
        return global_a[v]

    def safe_parse(val):
        if pd.isna(val): return None
        if isinstance(val, str):
            val = val.strip()
            if not val: return None
            try: return json.loads(val)
            except: pass
            try: return ast.literal_eval(val)
            except: pass
            try: return json.loads(val.replace("'", '"'))
            except: pass
            return None
        return val

    def recursive_remap(obj, flat_map_strategy="user"):
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                if pd.isna(v) or v is None:
                    new_dict[k] = v
                elif k == 'user_id':
                    new_dict[k] = get_u_id(v)
                elif k == 'track_id':
                    new_dict[k] = get_t_id(v)
                elif k == 'artist_id':
                    new_dict[k] = get_a_id(v)
                else:
                    new_dict[k] = recursive_remap(v, flat_map_strategy)
            return new_dict
        elif isinstance(obj, list):
            new_list = []
            for item in obj:
                if isinstance(item, (int, float, str)):
                    if flat_map_strategy == "user":
                        new_list.append(get_u_id(item))
                    elif flat_map_strategy == "track":
                        new_list.append(get_t_id(item))
                    else:
                        new_list.append(item)
                else:
                    new_list.append(recursive_remap(item, flat_map_strategy))
            return new_list
        else:
            return obj

    if 'track_id' in t_df.columns:
        t_df['track_id'] = t_df['track_id'].astype(str).map(lambda x: get_t_id(x) if pd.notna(x) else x).astype(int)
        
    for col in ['likes', 'dislikes', 'reactions']:
        if col in t_df.columns:
            t_df[col] = t_df[col].apply(lambda x: json.dumps(recursive_remap(safe_parse(x), "user"), ensure_ascii=False) if safe_parse(x) is not None else x)

    if 'artist_id' in a_df.columns:
        a_df['artist_id'] = a_df['artist_id'].astype(str).map(lambda x: get_a_id(x) if pd.notna(x) else x).astype(int)
        
    for col in ['likes', 'dislikes', 'reactions']:
        if col in a_df.columns:
            a_df[col] = a_df[col].apply(lambda x: json.dumps(recursive_remap(safe_parse(x), "user"), ensure_ascii=False) if safe_parse(x) is not None else x)

    if 'user_id' in u_df.columns:
        u_df['user_id'] = u_df['user_id'].astype(str).map(lambda x: get_u_id(x) if pd.notna(x) else x).astype(int)
        
    user_tracks_cols = ['uploaded_tracks', 'liked_tracks', 'disliked_tracks', 'reacted_tracks', 'likes_received', 'dislikes_received', 'reactions_received']
    for col in user_tracks_cols:
        if col in u_df.columns:
            u_df[col] = u_df[col].apply(lambda x: json.dumps(recursive_remap(safe_parse(x), "track"), ensure_ascii=False) if safe_parse(x) is not None else x)
            
    user_users_cols = ['liked_users', 'disliked_users', 'reacted_users', 'users_liked', 'users_disliked', 'users_reacted']
    for col in user_users_cols:
        if col in u_df.columns:
            u_df[col] = u_df[col].apply(lambda x: json.dumps(recursive_remap(safe_parse(x), "user"), ensure_ascii=False) if safe_parse(x) is not None else x)

    return t_df, a_df, u_df
