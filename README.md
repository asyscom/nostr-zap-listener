# nostr-zap-listener ⚡

A small Python bot that listens for NIP-57 zap receipts, replies with a thank-you,
and builds a **Weekly Zap Leaderboard** stored in SQLite.

## Features
- Listens to zap receipts (kind `9735`) across multiple relays
- Robust amount parsing:
  - `amount` tag (msat)
  - `bolt11` HRP with `m/u/n/p` suffixes (e.g. `lnbc300n…` → 30 sats)
  - `description.tags["amount"]` (msat) when present
- Customizable thank-you template
- Weekly leaderboard (manual or auto on each zap with debounce)
- SQLite persistence so data survives restarts

## Requirements
- Python 3.10+ recommended
- Linux/macOS (works fine on servers/VMs)

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
If you don't have `requirements.txt` yet, you can temporarily:
```bash
pip install python-dotenv python-nostr
```

## Configure
Copy `.env.example` to `.env` and edit it:
```bash
cp .env.example .env
nano .env
```

Key variables (see `.env.example` for all):
- `NSEC`: your private key in `nsec` format
- `RELAYS`: comma or space separated relay URLs
- `DB_PATH`: SQLite path (default: `./db/zaps.db`)
- `TOP_N`: how many users to show in the leaderboard
- `MIN_ZAP_SATS`: ignore micro-zaps below this (in sats)
- `REPLY_ON_UNKNOWN`: reply even if amount is unknown (1/0)
- `ALLOW_SELF_ZAP`: count self-zaps (1/0)
- `MIN_LEADERBOARD_INTERVAL`: debounce (seconds) for auto-leaderboard posts

## Run the listener
```bash
source .venv/bin/activate
python listen_zaps.py
```

## Publish the weekly leaderboard (manual)
```bash
source .venv/bin/activate
python publish_leaderboard.py --week 2025-W36
# If --week is omitted, it uses the previous ISO week.
```

## Auto-leaderboard (optional)
The listener can auto-post the leaderboard whenever a zap arrives (debounced).
Set in `.env`, for example:
```
TOP_N=10
MIN_LEADERBOARD_INTERVAL=300
```

## Project layout (suggested)
```
nostr-zap-listener/
├── .env.example
├── listen_zaps.py
├── publish_leaderboard.py
├── db/              # ignored by git; holds zaps.db
└── logs/            # ignored by git; optional runtime logs
```

## Safety
- **Never commit your real `.env`**. Only commit `.env.example`.
- Keep your `nsec` secret.

## Notes
- Signed commits (PGP/SSH) are welcome but optional.
- Different `nostr` library forks exist; we currently target `python-nostr`.
