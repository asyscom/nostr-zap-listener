#!/usr/bin/env python3
import os, sys, sqlite3, time, argparse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from nostr.key import PrivateKey, PublicKey
from nostr.event import Event
from nostr.relay_manager import RelayManager

def load_env():
    load_dotenv()
    NSEC   = os.getenv("NSEC", "").strip()
    RELAYS_RAW = os.getenv("RELAYS", "")
    # supporta separatori virgola, spazio o newline
    RELAYS = [r.strip() for chunk in RELAYS_RAW.split(",") for r in chunk.split() if r.strip()]
    DB     = os.getenv("DB_PATH", "./zaps.db")
    TOP_N  = int(os.getenv("TOP_N", "10"))
    return NSEC, RELAYS, DB, TOP_N

def prev_week_key(now_utc):
    ref = now_utc - timedelta(days=1)
    iso = ref.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"

def hex_to_npub(h):
    try:
        return PublicKey(bytes.fromhex(h)).bech32()
    except Exception:
        return h[:12] + "…"

def parse_args(default_top):
    p = argparse.ArgumentParser(description="Publish weekly Zap Leaderboard to Nostr")
    p.add_argument("--week", help="Settimana ISO (es. 2025-W36). Se omesso usa la settimana precedente.")
    p.add_argument("--top", type=int, default=default_top, help=f"Quanti utenti mostrare (default {default_top})")
    return p.parse_args()

def main():
    NSEC, RELAYS, DB, ENV_TOP = load_env()
    if not NSEC or not RELAYS:
        print("Missing NSEC/RELAYS in .env"); sys.exit(1)

    args = parse_args(ENV_TOP)
    now = datetime.now(timezone.utc)
    wk = args.week or prev_week_key(now)
    top_n = args.top

    sk = PrivateKey.from_nsec(NSEC)
    pk = sk.public_key

    conn = sqlite3.connect(DB)
    rows = conn.execute("""
      SELECT zapper_pubkey, SUM(amount_msat) AS tot_msat, COUNT(*) AS cnt
      FROM zaps
      WHERE week=?
      GROUP BY zapper_pubkey
      HAVING zapper_pubkey <> ''
      ORDER BY tot_msat DESC
      LIMIT ?
    """, (wk, top_n)).fetchall()

    if not rows:
        print(f"No zaps for week {wk}, nothing to post.")
        sys.exit(0)

    lines = [f"⚡ Weekly Zap Leaderboard — {wk}\n"]
    for rank, (who, tot_msat, cnt) in enumerate(rows, start=1):
        sats = (tot_msat or 0) // 1000
        lines.append(f"{rank}) {hex_to_npub(who)} — {sats:,} sats ({cnt} zaps)")

    content = "\n".join(lines)

    # Crea e firma l’evento
    event = Event(content=content, public_key=pk.hex(), kind=1, tags=[])
    sk.sign_event(event)

    print("NPUB:", pk.bech32())
    print("Relays:", RELAYS)

    # Pubblica
    rm = RelayManager()
    for url in RELAYS:
        rm.add_relay(url)
    rm.open_connections()
    time.sleep(1.25)
    rm.publish_event(event)
    time.sleep(1.0)
    rm.close_connections()

    print(f"Posted weekly leaderboard for {wk}.")

if __name__ == "__main__":
    main()

