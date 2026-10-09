# Deploying

The bot is a long-running worker using outbound Telegram long polling. It needs no public port. Persist `DATA_DIR`, protect `.env`, and run exactly one process per token. Competing pollers receive `409 Conflict`.

Run `npm run doctor` before startup. `/healthz` returns 200 after Telegram initialization and includes the route count.

## Docker Compose

```bash
cp .env.example .env
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml logs -f
```

The named volume preserves route mappings. Stop the old container before moving a token.

## systemd

Clone to `/opt/letta-telegram`, run `npm ci --omit=dev`, place a mode-600 environment file at `/etc/letta-telegram.env`, and install `deploy/systemd/letta-telegram.service`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now letta-telegram
journalctl -u letta-telegram -f
```

## Fly.io

Copy `fly.toml.example`, choose an app name, create a volume mounted at `/data`, set the three credential secrets plus `TELEGRAM_ADMIN_USER_IDS`, and deploy. Keep the worker count at one.

## Updates and backups

Stop intake, update the checkout, run `npm ci`, run both test gates, and restart. Back up `DATA_DIR`; Letta owns transcripts, while SQLite owns route-to-conversation mappings.
