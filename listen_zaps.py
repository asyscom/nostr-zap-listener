#!/usr/bin/env python3
import os, sys, time, json, sqlite3, secrets, re
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv

from nostr.key import PrivateKey, PublicKey
from nostr.event import Event
from nostr.relay_manager import RelayManager
from nostr.filter import Filter, Filters
from nostr.message_type import ClientMessageType

load_dotenv()
NSEC   = os.getenv("NSEC")
RELAYS = [r.strip() for r in (os.getenv("RELAYS") or "").split(",") if r.strip()]
DB     = os.getenv("DB_PATH", "./zaps.db")
MIN_ZAP_SATS   = int(os.getenv("MIN_ZAP_SATS", "50"))
THANK_TEMPLATE = os.getenv("THANK_TEMPLATE", "⚡ Thanks for the {sats} sats{who}! You're currently #{rank} this week. 🙏")
ALLOW_SELF_ZAP = os.getenv("ALLOW_SELF_ZAP", "0") == "1"
REPLY_ON_UNKNOWN = os.getenv("REPLY_ON_UNKNOWN", "1") == "1"

if not NSEC:   print("ERROR: NSEC missing in .env"); sys.exit(1)
if not RELAYS: print("ERROR: RELAYS missing in .env"); sys.exit(1)

# --- keys ---
sk = PrivateKey.from_nsec(NSEC)
pk = sk.public_key
ME_HEX = pk.hex()

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# --- db ---
conn = sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS zaps(
  event_id TEXT PRIMARY KEY,
  zapper_pubkey TEXT,
  note_id TEXT,
  amount_msat INTEGER,
  created_at INTEGER,
  week TEXT
)""")
conn.execute("""CREATE TABLE IF NOT EXISTS state(
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
)""")
conn.commit()

def get_state(k, default=None):
    row = conn.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
    return row[0] if row else default

def set_state(k, v):
    conn.execute("INSERT INTO state(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(k,str(v)))
    conn.commit()

def week_key(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{d.year}-W{d.week:02d}"

# ---- parser tags robusto (liste, dict, oggetti) ----
def parse_tag_list(ev, key):
    out = []
    tags = getattr(ev, "tags", []) or []
    for t in tags:
        k = v = None
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            k, v = t[0], t[1]
        elif isinstance(t, dict):
            k = t.get("name") or t.get("tag") or t.get(0)
            v = t.get("value") or t.get(1)
        else:
            k = getattr(t, "name", None) or getattr(t, "tag", None)
            v = getattr(t, "value", None)
            if v is None:
                vals = getattr(t, "values", None)
                if isinstance(vals, (list, tuple)) and len(vals) >= 2:
                    v = vals[1]
        if isinstance(k, str) and k == key and isinstance(v, str):
            out.append(v)
    return out

# ---- BOLT11 amount parser (decimali + m/u/n/p) ----
_BOLT11_HRP_RE = re.compile(r'^ln[a-z]{2,}([0-9]+(?:\.[0-9]+)?)([munp]?)1', re.IGNORECASE)

def msat_from_bolt11(pr: str):
    """
    Estrae l'importo dall'HRP dell'invoice BOLT11 e lo converte in msat.
    Usa la *regex* per trovare il separatore '1' DOPO l'unità (munp),
    così stringhe come 'lnbc210n1...' vengono interpretate come 21 sats (21000 msat).
    Esempi:
      lnbc300n1...   -> 30 sats  (300 * 100 msat)
      lnbc420n1...   -> 42 sats
      lnbc10.5u1...  -> 1_050 sats
      lnbc1m1...     -> 100_000 sats
    """
    try:
        if not pr:
            return None
        s = pr.strip().lower()
        m = _BOLT11_HRP_RE.match(s)
        if not m:
            return None

        num_str, suf = m.groups()
        val = Decimal(num_str)  # può essere decimale

        # 1 BTC = 100_000_000_000 msat
        if   suf == "m": msat = val * Decimal('1e8')        # mBTC
        elif suf == "u": msat = val * Decimal('1e5')        # μBTC
        elif suf == "n": msat = val * Decimal('1e2')        # nBTC
        elif suf == "p": msat =  val / Decimal('1e1')       # pBTC
        else:            msat = val * Decimal('1e11')       # BTC

        msat_int = int(msat)  # floor
        return msat_int if msat_int > 0 else None
    except Exception:
        return None

def hex_to_npub(hx):
    try:
        return PublicKey(bytes.fromhex(hx)).bech32()
    except Exception:
        return None

class _SafeDict(dict):
    def __missing__(self, k):
        return "{"+k+"}"

def make_thank_text(sats, unknown, rank, zapper_hex):
    sats_str = "⚡" if unknown else str(sats)
    npub = hex_to_npub(zapper_hex) if zapper_hex else None
    who = f" (nostr:{npub})" if npub else ""
    tpl = THANK_TEMPLATE or "⚡ Thanks for the {sats} sats{who}! You're currently #{rank} this week. 🙏"
    text = tpl.format_map(_SafeDict({"sats": sats_str, "rank": rank, "who": who}))
    text = text.replace("{sats}", sats_str).replace("{rank}", str(rank)).replace("{who}", who)
    return text

def parse_zap(ev):
    """
    Estrazione importo (msat) con priorità:
      1) description.tags['amount'] (msat)
      2) tag 'amount' nel receipt (msat)
      3) HRP dell'invoice 'bolt11' (→ msat)
    + sanity-cap via MAX_SANE_SATS (in sats, default 10_000_000)
    """
    MAX_SANE_SATS = int(os.getenv("MAX_SANE_SATS", "10000000"))

    res = {"sats":0, "unknown":True, "zapper_hex":None, "note_id":None,
           "recipients_in_desc":[], "recipients_in_event":[], "relays":[]}

    ms_desc = None
    ms_receipt = None
    ms_hrp = None

    # --- description JSON (zap request) ---
    desc = parse_tag_list(ev, "description")
    if desc:
        try:
            dj = json.loads(desc[0])
            if isinstance(dj, dict):
                res["zapper_hex"] = dj.get("pubkey") or res["zapper_hex"]
                for tg in dj.get("tags") or []:
                    if isinstance(tg, list) and tg:
                        t0 = tg[0]
                        if t0 == "e" and len(tg) > 1 and not res["note_id"]:
                            res["note_id"] = tg[1]
                        elif t0 == "p" and len(tg) > 1:
                            res["recipients_in_desc"].append(tg[1])
                        elif t0 == "relays":
                            for u in tg[1:]:
                                if isinstance(u, str) and u.startswith("wss://"):
                                    res["relays"].append(u.strip())
                        elif t0 == "amount" and len(tg) > 1:
                            try:
                                ms_desc = int(str(tg[1]).strip())
                                print(f"DEBUG desc.tags amount → msat={ms_desc}")
                            except Exception:
                                pass
        except Exception:
            pass

    # --- amount msat sul receipt ---
    amt = parse_tag_list(ev, "amount")
    if amt:
        try:
            ms_receipt = int(amt[0])
            print(f"DEBUG receipt amount → msat={ms_receipt}")
        except Exception:
            pass

    # --- HRP dall'invoice ---
    bolt = parse_tag_list(ev, "bolt11")
    if bolt:
        ms_hrp = msat_from_bolt11(bolt[0])
        print(f"DEBUG bolt11 parse → msat={ms_hrp} (bolt11={bolt[0][:24]}…)")

    # --- scelta finale (priorità + sanity cap) ---
    candidates = [ms for ms in (ms_desc, ms_receipt, ms_hrp) if isinstance(ms, int) and ms > 0]
    if candidates:
        ms = candidates[0]  # ms_desc vince se presente
        # sanity cap: scarta importi > MAX_SANE_SATS
        if ms // 1000 > MAX_SANE_SATS:
            # prova un altro candidato “ragionevole”
            ok = [x for x in candidates if x // 1000 <= MAX_SANE_SATS]
            ms = ok[0] if ok else None
    else:
        ms = None

    if ms:
        res["sats"] = ms // 1000
        res["unknown"] = False

    # destinatari sull'evento (p/P)
    res["recipients_in_event"] = parse_tag_list(ev, "p") + parse_tag_list(ev, "P")

    # fallback zapper/note
    if not res["zapper_hex"]:
        P = parse_tag_list(ev,"P")
        if P: res["zapper_hex"]=P[0]
    if not res["note_id"]:
        e = parse_tag_list(ev,"e")
        if e: res["note_id"]=e[0]

    # DEBUG extra se ancora sconosciuto
    if res["unknown"]:
        try:
            print("DEBUG unknown amt — RAW TAGS:", getattr(ev, "tags", None))
            if desc:
                print("DEBUG description JSON:", desc[0][:400])
        except Exception:
            pass

    return res

def _broadcast_with_relays(ev: Event, relays: list):
    rm2 = RelayManager()
    for r in relays: rm2.add_relay(r)
    rm2.open_connections(); time.sleep(1.25); rm2.publish_event(ev); time.sleep(0.75); rm2.close_connections()

def safe_publish_event(rm: RelayManager, ev: Event, extra_relays=None):
    extra_relays = extra_relays or []
    try:
        rm.publish_event(ev)
    except Exception as e:
        log(f"Warn: publish_event failed: {e} → using fresh RelayManager")
        try:
            all_relays = list(dict.fromkeys([*RELAYS, *extra_relays]))
            _broadcast_with_relays(ev, all_relays); return
        except Exception as e2:
            log(f"ERROR: final publish_event failed: {e2}"); return
    extra_only = [u for u in extra_relays if u not in RELAYS]
    if extra_only:
        try: _broadcast_with_relays(ev, extra_only)
        except Exception as e3: log(f"Warn: extra broadcast failed: {e3}")

def rank_for_week(zapper_hex, wk):
    rows = conn.execute(
        "SELECT zapper_pubkey, SUM(amount_msat) AS tot FROM zaps WHERE week=? GROUP BY zapper_pubkey ORDER BY tot DESC",
        (wk,)
    ).fetchall()
    for i,(who,_) in enumerate(rows, start=1):
        if who==zapper_hex:
            return i
    return 1

def main():
    since = int(get_state("last_since", str(int(time.time()) - 86400)))
    sub_id = "zaps_" + secrets.token_hex(4)
    filters = Filters([Filter(kinds=[9735], since=since)])

    rm = RelayManager()
    for url in RELAYS: rm.add_relay(url)
    rm.add_subscription(sub_id, filters); rm.open_connections(); time.sleep(2.0)

    req = [ClientMessageType.REQUEST, sub_id]; req.extend(filters.to_json_array())
    try: rm.publish_message(json.dumps(req))
    except Exception as e: log(f"Warn: REQUEST publish failed: {e}")

    log(f"Listening receipts to {pk.bech32()} (since {since}) on {len(RELAYS)} relays…")
    try:
        while True:
            while rm.message_pool.has_events():
                ev_msg = rm.message_pool.get_event(); ev = ev_msg.event
                if ev.kind != 9735: continue

                data = parse_zap(ev)
                rec_desc, rec_ev = set(data["recipients_in_desc"]), set(data["recipients_in_event"])
                match_desc, match_ev = (ME_HEX in rec_desc), (ME_HEX in rec_ev)
                match_self = (ALLOW_SELF_ZAP and data["zapper_hex"] == ME_HEX)
                if not (match_desc or match_ev or match_self):
                    continue

                try:
                    conn.execute(
                        "INSERT INTO zaps(event_id, zapper_pubkey, note_id, amount_msat, created_at, week) VALUES(?,?,?,?,?,?)",
                        (ev.id, data.get("zapper_hex") or "", data.get("note_id") or "",
                         data["sats"]*1000, ev.created_at, week_key(ev.created_at))
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass

                if ev.created_at and ev.created_at > since:
                    since = ev.created_at; set_state("last_since", since)

                sats = data["sats"]; unknown = data["unknown"]
                zapper_hex = (data.get("zapper_hex") or "unknown"); note_id = data.get("note_id")

                should_reply = (sats >= MIN_ZAP_SATS) or (unknown and REPLY_ON_UNKNOWN)
                if not should_reply: continue

                rank = rank_for_week(zapper_hex, week_key(ev.created_at or int(time.time())))
                text = make_thank_text(sats, unknown, rank, zapper_hex)

                tags = []
                if zapper_hex and zapper_hex != "unknown": tags.append(["p", zapper_hex])
                if note_id: tags.append(["e", note_id, "", "reply"])

                reply = Event(content=text, public_key=ME_HEX, kind=1, tags=tags)
                sk.sign_event(reply)

                extra = [u for u in (data.get("relays") or []) if isinstance(u, str) and u.startswith("wss://")]
                safe_publish_event(rm, reply, extra_relays=extra)
                log(f"Published reply id={reply.id[:8]}… text='{text}'")
                time.sleep(0.5)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        rm.close_connections()

if __name__ == "__main__":
    main()

