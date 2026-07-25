# Deploying SUTMusic app

## GitHub Action

`.github/workflows/deploy-app.yml` runs on every push to `project` that touches
`app/**`. It:

1. rsyncs `app/` to `/srv/bots/telegram/SUTMusic_app/app` on the server
   (leaving `.venv`, `node_modules`, `__pycache__`, and the 5 runtime log
   files alone).
2. Over SSH, copies the session files and `.env` out of
   `/srv/bots/telegram/SUTMusic_app/secrets/` into place, refreshes the
   installed systemd unit, and runs
   `systemctl --user restart sutmusic.service`.

### Required repo secrets

| Secret       | Value                                   |
|--------------|------------------------------------------|
| `SSH_HOST`   | Server IP / hostname                     |
| `SSH_USER`   | Non-root deploy user (e.g. `max`)        |
| `SSH_PORT`   | SSH port                                 |
| `SSH_KEY`    | Private key for `SSH_USER`, PEM format   |

## One-time server setup

These happen once, by hand, before the Action ever runs:

```bash
# as the deploy user, e.g. max -- no sudo needed for any of this
mkdir -p /srv/bots/telegram/SUTMusic_app/app
mkdir -p /srv/bots/telegram/SUTMusic_app/secrets
mkdir -p /srv/bots/telegram/SUTMusic_app/app/db/internal_db
mkdir -p /srv/bots/telegram/SUTMusic_app/app/db/external_db

# put the real secrets here once -- the Action copies from here on every deploy
cp internal_db_session.session /srv/bots/telegram/SUTMusic_app/secrets/
cp external_db_session.session /srv/bots/telegram/SUTMusic_app/secrets/
cp .env /srv/bots/telegram/SUTMusic_app/secrets/

# create the venv the Action will keep reusing/updating
cd /srv/bots/telegram/SUTMusic_app/app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# install cloudflared if not already present, then install the user unit
mkdir -p ~/.config/systemd/user
cp deploy/sutmusic.service ~/.config/systemd/user/sutmusic.service
systemctl --user daemon-reload
systemctl --user enable --now sutmusic.service

# let the service survive after this SSH session ends, and start on boot
loginctl enable-linger max
```

## What the service does

`sutmusic.service` (a systemd **user** unit -- runs with `systemctl --user`,
no root ever required, which is why the GitHub Action can drive it as a
plain non-root SSH user) runs `deploy/start.sh` in the foreground, which:

- activates the existing `.venv` and runs `pip install -r requirements.txt`
  to pick up anything new
- starts the Telegram bot (`python main.py`) -> `app/app.log`
- starts the webapp (`uvicorn webapp.main:app --host 0.0.0.0 --port 8000
  --reload`) -> `app/webapp.log`
- runs `npm install && npm run build && npm run preview` for the frontend
  -> `app/frontend.log`
- starts `cloudflared tunnel --protocol quic --url http://localhost:4173`
  -> `app/cloudflare.log`
- watches `cloudflare.log` for the public `*.trycloudflare.com` URL and
  writes it to `app/url.txt`
- supervises all four processes: if any one dies, it tears the rest down
  and exits non-zero, so systemd's `Restart=always` brings the whole stack
  back up together instead of leaving mismatched processes running.
