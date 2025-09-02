#!/usr/bin/env bash
set -euo pipefail

echo "==> Repo bootstrap starting..."

# Ensure we're inside a git repo
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This doesn't look like a git repo. Run inside your project folder."
  exit 1
fi

# Ensure branch is 'main'
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "main" ]; then
  git branch -M main || true
fi

# Create runtime folders and move runtime files if present
mkdir -p db logs
[ -f zaps.db ] && mv -n zaps.db db/ || true
[ -f leaderboard.log ] && mv -n leaderboard.log logs/ || true
touch db/.gitkeep logs/.gitkeep

# Create README.md if missing (leave existing intact)
if [ ! -f README.md ]; then
  cat > README.md <<'EOF'
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
EOF
fi

# requirements.txt (create if missing)
if [ ! -f requirements.txt ]; then
  cat > requirements.txt <<'EOF'
python-dotenv>=1.0.1
python-nostr>=1.6.0
EOF
fi

# LICENSE (MIT) (create if missing)
if [ ! -f LICENSE ]; then
  cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2025 

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights  
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell      
copies of the Software, and to permit persons to do so, subject to the        
following conditions:                                                         

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.                               

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR    
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,       
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE   
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER        
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE 
SOFTWARE.
EOF
fi

# VERSION (create if missing)
[ -f VERSION ] || echo "0.1.0" > VERSION

# CHANGELOG.md (create if missing)
if [ ! -f CHANGELOG.md ]; then
  cat > CHANGELOG.md <<'EOF'
# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.1.0] - 2025-09-02
### Added
- Initial public release: zap listener, robust amount parsing, thank-you replies.
- Weekly leaderboard script.
- `.env.example`, `requirements.txt`, README, MIT license.
EOF
fi

# .gitignore (overwrite with sane defaults)
cat > .gitignore <<'EOF'
# env
.env
*.env

# python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.venv/
venv/

# DB & logs (keep folders but ignore contents)
db/*
!db/.gitkeep
logs/*
!logs/.gitkeep
*.db
*.sqlite*
*.log

# OS / editor
.DS_Store
*.swp
*.swo
EOF

# .env.example (create if missing)
if [ ! -f .env.example ]; then
  cat > .env.example <<'EOF'
# Your Nostr NSEC (private key in nsec format)
NSEC=nsec1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Default relays (you can add/remove your favorites, comma or space separated)
RELAYS=wss://relay.davidebtc.me, wss://nos.lol, wss://nostr-pub.wellorder.net, wss://nostr.hifish.org, wss://nostr.0x7e.xyz, wss://nostr.massmux.com, wss://relay.damus.io, wss://relay.nostrplebs.com, wss://relay.primal.net

# Optional settings (defaults in parentheses)

# Reply to zap receipts with unknown amounts (1 = yes, 0 = no) (default 1)
REPLY_ON_UNKNOWN=1

# Allow self-zaps to count and trigger replies (1 = yes, 0 = no) (default 0)
ALLOW_SELF_ZAP=1

# Ignore micro-zaps below this threshold in sats (default 50)
MIN_ZAP_SATS=20

# Thank-you message template
# Available placeholders: {sats}, {who}, {rank}
THANK_TEMPLATE="⚡ Thanks for the {sats} sats{who}! You're currently #{rank} this week. 🙏"

# How many users to show in the leaderboard (default 10)
TOP_N=10

# SQLite database path (repo-local)
DB_PATH=./db/zaps.db

# Auto-leaderboard publish debounce in seconds (default 300). Lower = more “live”.
# MIN_LEADERBOARD_INTERVAL=300
EOF
fi

# Stage & commit
git add -A
if git diff --cached --quiet; then
  echo "Nothing to commit."
else
  git commit -S -m "docs: add base docs and config; repo bootstrap"
fi

# Ensure remote is set
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "No remote 'origin' set. Set it then run: git push -u origin main"
  exit 0
fi

# Tag if missing
if ! git rev-parse -q --verify "refs/tags/v0.1.0" >/dev/null; then
  git tag -s v0.1.0 -m "v0.1.0" || echo "Warning: could not create signed tag v0.1.0 (check GPG)."
fi

# Push with tags
git push -u origin main --follow-tags || {
  echo "Push failed. Check your SSH/HTTPS permissions or remote state."
  exit 1
}

echo "==> Done. Repo is bootstrapped and pushed."
