import pandas as pd

def normalize_texts(df_tracks, df_artists, df_users):
    t_df = df_tracks.copy()
    a_df = df_artists.copy()
    u_df = df_users.copy()
    
    def process_str(text):
        if pd.isna(text):
            return text
        if isinstance(text, str):
            return text.strip().lower()
        return text

    # Text columns typical in Tracks
    str_cols_t = ['track_name', 'artist_names', 'sender_usernames']
    for col in str_cols_t:
        if col in t_df.columns:
            t_df[col] = t_df[col].apply(process_str)

    # Text columns typical in Artists
    str_cols_a = ['artist_name']
    for col in str_cols_a:
        if col in a_df.columns:
            a_df[col] = a_df[col].apply(process_str)

    # Text columns typical in Users
    str_cols_u = ['username', 'first_name', 'last_name', 'language']
    for col in str_cols_u:
        if col in u_df.columns:
            u_df[col] = u_df[col].apply(process_str)
            
    return t_df, a_df, u_df
