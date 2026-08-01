# What's in this update

## 1. Changed: `.github/workflows/deploy-engine.yml`

Old behavior: triggered on `engine/**`, always deployed that one folder.

New behavior:
- Triggers on any `engine_v*/**` path (`engine_v1/**`, `engine_v2/**`, and any
  future `engine_v3/**`, etc. -- no further edits needed when a new engine
  version is added later).
- On each push, it looks at exactly which `engine_v*` folder(s) changed in
  that push (via `git diff` between the push's before/after commits).
- If only one `engine_v*` changed, that one is deployed.
- If more than one changed in the same push, the **highest version number**
  among the changed ones is deployed (e.g. touching both `engine_v1/` and
  `engine_v2/` in one push deploys `engine_v2`).
- Whichever folder is selected gets rsynced into the server's single
  `/srv/bots/telegram/SUTMusic_app/engine/` folder (same target path, same
  `--delete`, same excludes, same `sutengine.service` restart as before) --
  so there is still only ever one engine running on the server.
- Everything else (the `deploy-app.yml` workflow, the server-side
  `engine/` folder structure, the `sutengine.service` / `sutmusic.service`
  split, secrets handling) is unchanged.

No action needed on the server for this part -- the workflow still writes
to the exact same path and restarts the exact same systemd unit.

## 2. New: `engine_v2/` connector files

The new design team's `engine_v2/` folder (as handed off) only contained the
notebook, `Manual.txt`, and `Summary.md` describing the new two-stage
ensemble model (artist-ranking + track-reranking) -- it had no service
wrapper. Added so it plugs in exactly like `engine_v1/` did:

- **`main.py`** -- same FastAPI app, same four endpoints
  (`/health`, `/suggest`, `/recommend`, `/onboarding`), same query params,
  same JSON response shapes as `engine_v1/main.py`. This is what makes it a
  drop-in replacement: `app/webapp/engine_client.py` (and everything that
  calls it -- `routers/suggestions.py`, `repository.py`) needs **zero
  changes**, because it only ever spoke to the HTTP contract, never to
  engine internals.
- **`recommender.py`** -- the actual ensemble logic per `Manual.txt` /
  `Summary.md`: an artist-level ranking stage followed by a track-level
  re-ranking stage, with the same fallback precedence as v1 (trained
  profile -> reacted artists -> reacted tracks -> global popularity).
- **`requirements.txt`, `setup_venv.sh`, `.env.example`,
  `deploy/start.sh`, `deploy/sutengine.service`** -- same shape as
  `engine_v1`'s, so whichever folder lands on the server as `engine/` runs
  under the identical systemd unit without any server-side changes.
- **`model_params/`** -- empty placeholder (matches how `engine_v1/model_params/`
  ships in the repo too; the actual trained artifacts are dropped in
  out-of-band, same as today). Note: the handed-off `Manual.txt` calls this
  folder `model_params_colab` -- it's renamed to `model_params/` here to
  match the standard structure both engines use on the server. Make sure
  whatever gets exported from the training notebook going forward is
  placed under `model_params/`, not `model_params_colab/`.
- **`README.md`** -- full contract + file-layout write-up, mirroring
  `engine_v1/README.md`.

I did not touch `engine_v2/Manual.txt`, `Summary.md`, or `engine_new.ipynb`
(the other team's docs/notebook) other than including them unchanged in
this folder for completeness.

## Not changed

- `app/**` and `.github/workflows/deploy-app.yml` -- untouched.
- `engine_v1/**` -- untouched, still deployable on its own exactly as
  before.
- Server-side folder structure, systemd units, and secrets flow -- all
  unchanged; the workflow still writes to the same `engine/` path and
  restarts the same `sutengine.service`.

## Verified before packaging

- Both new Python files pass `python -m py_compile`.
- `recommender.py`'s pipeline (trained-profile, reacted-artist, and
  reacted-track paths, nudge, popularity fallback, onboarding) was
  exercised against a synthetic `model_params/` set and produces sane,
  correctly-shaped output for every path.
- `main.py`'s FastAPI app was exercised end-to-end (`/health`, `/suggest`,
  `/recommend`, `/onboarding`, including the "everything excluded -> 404"
  edge case) via `TestClient` against the same synthetic data.
- The workflow's folder-selection shell logic was run against a real throwaway
  git repo for three cases: only `engine_v1` changed, both `engine_v1` and
  `engine_v2` changed in one push (correctly picks `engine_v2`), and an
  app-only change (correctly yields nothing to deploy).
