============================================================
MODEL LOGIC AND WORKING EXPLANATION
============================================================

This document explains the reasoning, architecture, and
mechanism behind the ensemble recommendation model used in
the Telegram music bot. It is intended for developers and
researchers who want to understand how the model works
internally.

------------------------------------------------------------
1. PROBLEM AND GOAL
------------------------------------------------------------

We have a university‑group Telegram chat where thousands of
users share music files. Members react to these files using
emojis (like, fire, heart, etc.). Our goal is to build a bot
that can recommend unheard songs to a user based solely on
their emoji reaction history and the community’s collective
behaviour.

The data is extremely sparse (1.7% interaction density),
contains social noise (dislikes are retaliatory), and lacks
audio features. The core challenge is to extract reliable
music‑taste signals from this sparse, noisy data.

------------------------------------------------------------
2. TWO‑STAGE ENSEMBLE: ARTIST‑FIRST + TRACK RE‑RANKING
------------------------------------------------------------

Track‑level collaborative filtering alone fails because most
tracks have very few reactions. However, artist‑level
preferences are much denser and more stable. Therefore:

Stage 1 – Artist Model:
  Build a user‑artist interaction matrix and train a hybrid
  matrix factorisation model to learn user and artist
  embeddings. At recommendation time, we rank all artists for
  a user and select the top N artists.

Stage 2 – Track Model:
  From those top artists, we collect unseen tracks. A separate
  track‑level BPR‑MF model re‑ranks these candidates using
  learned user‑track embeddings. The final list of 10 tracks
  is returned.

This ensemble combines the broad‑taste power of the artist
model with the fine‑grained ranking of the track model,
overcoming the sparsity that plagued pure track‑level
approaches.

------------------------------------------------------------
3. BUILDING THE USER‑ARTIST MATRIX
------------------------------------------------------------

We aggregate positive signals from three sources:

- Track reactions: each reaction with a score > 1.0
  (from reaction_types.csv) is counted. The score (e.g., 4.5
  for 🔥, 4.0 for ❤️) is used as a weight.
- Artist reactions: direct reactions to artist messages
  (separate table) are treated similarly.
- Uploads: a user uploading a track is a strong preference
  signal. It contributes a fixed high weight (UPLOAD_WEIGHT)
  to the track's primary artist.

All artist IDs are first deduplicated via canonical mapping
(artist names normalised and merged). The matrix is stored as
a sparse binary matrix for BPR sampling and a parallel weight
matrix for loss weighting.

Additionally, we inject synthetic interactions from
related‑artist edges (from artist_links.csv, derived from
Last.fm metadata). For every user who likes an artist A, we
add a low‑weight edge to each related artist B (if the user
hasn't already interacted with B). This spreads collaborative
signal along the artist similarity graph.

------------------------------------------------------------
4. HYBRID ARTIST MODEL (HybridArtistMF)
------------------------------------------------------------

The artist model uses matrix factorisation with side features.

Input:
- user_id (index)
- artist_id (index)
- genre_features: a 361‑dimensional binary vector (or padded)
  derived from cleaned Last.fm genre tags.

Architecture:
- User embedding: an ID‑based vector of size EMBEDDING_DIM.
- Artist embedding: a combination of an ID‑based vector
  (artist_id_emb) and a learned projection of the genre
  features (genre_proj).
  final_artist_emb = artist_id_emb + genre_proj(genre_features)
- Biases: user_bias and artist_bias are added to the dot product.

Prediction:
  score(user, artist) = user_emb · artist_emb + user_bias + artist_bias

Training uses two losses:

1. Weighted BPR (Bayesian Personalized Ranking):
   For each observed (user, artist) pair with weight w, we
   sample a random unobserved artist as a negative. The loss
   pushes the score of the positive artist above the negative
   artist. The weight w ensures that strong signals (high
   reaction score, uploads) dominate the gradient.

2. Edge loss (regularisation):
   For each related‑artist edge (A, B) we minimise the squared
   distance between their embeddings. This pulls similar
   artists closer in the latent space.

Total loss = weighted_BPR_loss + λ * edge_loss

The model is trained with Adam optimizer and cosine annealing
scheduler for 200 epochs.

------------------------------------------------------------
5. TRACK MODEL (TrackMF)
------------------------------------------------------------

A simple matrix factorisation model (no side features) trained
on the user‑track interaction matrix (binary, from positive
track reactions only). It learns user and track embeddings
using standard BPR loss.

This model is used only for re‑ranking candidates proposed by
the artist model. Because it only needs to compare a small set
of tracks (typically ~100), it remains effective despite the
overall sparsity.

------------------------------------------------------------
6. RECOMMENDATION GENERATION (ENSEMBLE PIPELINE)
------------------------------------------------------------

Given a user (by original user_id):

a) Artist ranking:
   - Retrieve the user's artist‑model embedding (pre‑trained or
     averaged from liked artists).
   - Compute dot product with all artist embeddings.
   - Keep the top N_ARTISTS (default 15) artists.

b) Candidate collection:
   - For each top artist, collect all tracks that the user has
     never interacted with (using the seen_tracks set).
   - This yields a candidate pool of typically 50–200 tracks.

c) Track re‑ranking (if user has a track‑model embedding):
   - For each candidate track, compute dot product between the
     user's track‑model embedding and the track embedding.
   - Sort by score and return the top K (10) tracks.

d) If the user does not have a track‑model embedding
   (e.g., cold start), fall back to sorting candidates by
   global popularity (track_pop).

------------------------------------------------------------
7. COLD‑START AND SINGLE‑USER UPDATES
------------------------------------------------------------

Cold‑start (new user):
- Present onboarding tracks from diverse popular artists.
- After one or more positive reactions, compute the user's
  artist‑model embedding as the mean of the embeddings of the
  artists of the reacted tracks.
- Run the same pipeline, using popularity for track re‑ranking.

Single‑user update (no retraining):
- When a user reacts to new tracks, recompute their
  artist‑model embedding as the (weighted) mean of the
  embeddings of all artists they have ever positively
  interacted with. Similarly, recompute their track‑model
  embedding as the mean of the embeddings of their liked tracks.
- This takes < 1 ms and ensures the bot always sees the
  freshest profile.

The artist and track embeddings are fixed; only the user's
representation changes.

------------------------------------------------------------
8. KEY INSIGHTS AND DESIGN CHOICES
------------------------------------------------------------

- Positive reactions are genuine taste signals; dislikes are
  socially driven and are ignored. No debiasing is needed.
- Artist‑level aggregation drastically reduces sparsity.
- Limiting the number of top artists (N_ARTISTS = 15) prevents
  noisy candidates from diluting the recommendation.
- Weighting interactions by reaction score improves ranking
  quality.
- Synthetic related‑artist edges inject external knowledge
  into the collaborative matrix, enabling discovery of new
  artists.
- Genre features help cold‑start artists who lack interactions.
- The ensemble architecture separates broad taste (artist model)
  from track‑level fine‑ranking, allowing each model to
  specialise.
- The entire system can be updated for a single user instantly
  by recomputing their embedding as the centroid of their
  interacted items.

------------------------------------------------------------
9. TRAINING SUMMARY
------------------------------------------------------------

Data: processed/*.csv + artist_dedup_mapping.csv +
      artist_links.csv + artist_genre_matrix_final.npz

Artists are deduplicated. The user‑artist matrix is built,
augmented with related‑artist edges, and weighted. The
artist model is trained for 200 epochs with weighted BPR
and edge loss. The track model is trained on the
user‑track matrix for 150 epochs. Both models are exported
along with encoders and precomputed embeddings for
lightning‑fast inference.

The final ensemble achieves ~11.1% Recall@10 and ~8.4%
Precision@10 on a hold‑out test set, which is excellent for
such a sparse dataset.

============================================================
END OF EXPLANATION
============================================================
