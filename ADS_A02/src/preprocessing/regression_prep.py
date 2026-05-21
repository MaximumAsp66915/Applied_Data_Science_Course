import pandas as pd
import numpy as np
import os

def prepare_regression_data(tracks_path, artists_path, users_path, output_dir):
    """
    Reads the base datasets, filters and engineers features specifically for Regression tasks,
    and returns the new DataFrames while saving them as CSV files.
    """
    df_tracks = pd.read_csv(tracks_path)
    df_artists = pd.read_csv(artists_path)
    df_users = pd.read_csv(users_path)

    # -----------------------------
    # 1. Process reg_users
    # -----------------------------
    users_keep_cols = [
        'user_id', 'num_likes', 'num_dislikes', 'num_reactions', 'num_likes_received',
        'num_dislikes_received', 'num_reactions_received', 'num_liked_users',
        'num_disliked_users', 'num_reacted_users', 'num_users_liked',
        'num_users_disliked', 'num_users_reacted'
    ]
    df_reg_users = df_users[users_keep_cols].copy()
    
    def count_uploaded_tracks(x):
        if pd.isna(x) or str(x).strip() == '':
            return 0
        return len(str(x).split(','))
        
    df_reg_users['num_uploaded_tracks'] = df_users['uploaded_tracks'].apply(count_uploaded_tracks)

    # -----------------------------
    # 2. Process reg_artists
    # -----------------------------
    artists_keep_cols = ['artist_id', 'num_likes', 'num_dislikes', 'num_reactions']
    df_reg_artists = df_artists[artists_keep_cols].copy()

    # -----------------------------
    # 3. Process reg_tracks
    # -----------------------------
    # Create mappings
    artist_map = dict(zip(df_artists['artist_name'].astype(str), df_artists['artist_id']))
    chat_id_map = dict(zip(df_users['chat_id'].astype(str), df_users['user_id']))

    def map_artist_names_to_ids(names_str):
        if pd.isna(names_str) or str(names_str).strip() == '':
            return ''
        names = [n.strip() for n in str(names_str).split(',')]
        ids = [str(artist_map.get(n, '')) for n in names if n in artist_map]
        return ','.join(ids)

    def map_chat_ids_to_user_ids(chat_ids_str):
        if pd.isna(chat_ids_str) or str(chat_ids_str).strip() == '':
            return ''
        c_ids = [c.strip() for c in str(chat_ids_str).split(',')]
        u_ids = [str(chat_id_map.get(c, '')) for c in c_ids if c in chat_id_map]
        return ','.join(u_ids)

    # Keep track_id, num_senders and total_reactions for regression tasks
    df_reg_tracks = df_tracks[['track_id', 'num_senders', 'total_reactions']].copy()
    df_reg_tracks['artist_ids'] = df_tracks['artist_names'].apply(map_artist_names_to_ids)
    df_reg_tracks['sender_ids'] = df_tracks['sender_chat_ids'].apply(map_chat_ids_to_user_ids)

    # -----------------------------
    # 4. Save to processed folder
    # -----------------------------
    os.makedirs(output_dir, exist_ok=True)
    df_reg_users.to_csv(os.path.join(output_dir, 'reg_users.csv'), index=False)
    df_reg_artists.to_csv(os.path.join(output_dir, 'reg_artists.csv'), index=False)
    df_reg_tracks.to_csv(os.path.join(output_dir, 'reg_tracks.csv'), index=False)

    return df_reg_tracks, df_reg_artists, df_reg_users


