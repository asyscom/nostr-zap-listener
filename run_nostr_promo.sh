#!/usr/bin/env bash
set -Eeuo pipefail

# Evita esecuzioni multiple sovrapposte
LOCK="/tmp/nostr_promo.lock"
exec 9>"$LOCK"
flock -n 9 || exit 0

# NON eseguire prima di settembre 2025, a meno che non forzi
if [[ "${FORCE:-0}" != "1" ]] && [[ "$(date +%Y%m)" -lt "202509" ]]; then
  exit 0
fi

cd /home/ubuntu/bot_nostr
source .venv/bin/activate
python /home/ubuntu/bot_nostr/post_nostr.py

