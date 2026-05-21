import pandas as pd
import numpy as np

def aggregate_track_features(df_tracks, df_artists, df_users):
    """
    Takes the regression DataFrames and aggregates artist and user metrics 
    into the tracks dataframe, thereby replacing the csv-string id columns 
    with summed numeric columns.
    """
    df_tracks = df_tracks.copy()
    
    # Convert IDs to strings for robust dictionary lookup
    artist_dict = {str(k): v for k, v in df_artists.set_index('artist_id').to_dict('index').items()}
    user_dict = {str(k): v for k, v in df_users.set_index('user_id').to_dict('index').items()}
    
    artist_cols = ['num_likes', 'num_dislikes', 'num_reactions']
    user_cols = [c for c in df_users.columns if c != 'user_id']
    
    artist_agg = []
    user_agg = []
    
    for _, row in df_tracks.iterrows():
        # --- Artist Aggregation ---
        a_ids_str = str(row['artist_ids']) if 'artist_ids' in row else ''
        a_ids = [x.strip() for x in a_ids_str.split(',')] if a_ids_str and a_ids_str.lower() != 'nan' else []
        
        a_vals = {c: 0 for c in artist_cols}
        for a_id in a_ids:
            if a_id in artist_dict:
                for c in artist_cols:
                    a_vals[c] += artist_dict[a_id].get(c, 0)
        artist_agg.append(a_vals)
        
        # --- Sender (User) Aggregation ---
        s_ids_str = str(row['sender_ids']) if 'sender_ids' in row else ''
        s_ids = [x.strip() for x in s_ids_str.split(',')] if s_ids_str and s_ids_str.lower() != 'nan' else []
        
        s_vals = {c: 0 for c in user_cols}
        for s_id in s_ids:
            if s_id in user_dict:
                for c in user_cols:
                    val = user_dict[s_id].get(c, 0)
                    s_vals[c] += (val if pd.notna(val) else 0)
        user_agg.append(s_vals)

    # Convert aggregated dictionaries into DataFrames
    df_artist_agg = pd.DataFrame(artist_agg)
    df_user_agg = pd.DataFrame(user_agg)
    
    # Rename columns to meet spec: "artists_total_likes", "senders_total_dislikes", etc.
    def rename_artist_col(c):
        suffix = c[4:] if c.startswith('num_') else c
        return f"artists_total_{suffix}"
        
    def rename_user_col(c):
        suffix = c[4:] if c.startswith('num_') else c
        return f"senders_total_{suffix}"

    df_artist_agg = df_artist_agg.rename(columns={c: rename_artist_col(c) for c in artist_cols})
    df_user_agg = df_user_agg.rename(columns={c: rename_user_col(c) for c in user_cols})
    
    # Concatenate with the original tracks DataFrame (align indexes)
    df_tracks_new = pd.concat([
        df_tracks.reset_index(drop=True), 
        df_artist_agg.reset_index(drop=True), 
        df_user_agg.reset_index(drop=True)
    ], axis=1)
                               
    # Drop the original string ID columns
    cols_to_drop = [c for c in ['artist_ids', 'sender_ids'] if c in df_tracks_new.columns]
    if cols_to_drop:
        df_tracks_new = df_tracks_new.drop(columns=cols_to_drop)
        
    return df_tracks_new
