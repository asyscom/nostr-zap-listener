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
_BOLT11_HRP_RE = re.compile(r'^ln\w{2,}([0-9]+(?:\.[0-9]+)?)([munp]?)(1)', re.IGNORECASE)
def msat_from_bolt11(pr: str):
    """
    Estrae amount dall'HRP del BOLT11 e lo converte in msat
    SENZA regex: prende tutto tra 'ln<currency>' e il primo '1'.
    Esempi:
      lnbc300n1...  -> 300n   -> 300 * 100 msat   = 30_000 msat  (30 sats)
      lnbc420n1...  -> 420n   -> 420 * 100 msat   = 42_000 msat  (42 sats)
      lnbc10.5u1... -> 10.5u  -> 10.5 * 100_000   = 1_050_000 msat (1_050 sats)
      lnbc1p1...    -> 1p     -> 1 / 10           = 0.1 msat  (≈0 → 0 msat)
    """
    try:
        s = pr.strip().lower()
        if not s.startswith("ln"):
            return None

        # trova il separatore '1' (inizio della data part)
        pos1 = s.find("1")
        if pos1 < 0:
            return None

        # hrp dopo 'ln' e prima di '1' (es: 'bc300n' oppure solo 'bc' se amountless)
        hrp_body = s[2:pos1]  # skip 'ln'

        # salta il prefisso alfabetico di valuta (es: 'bc', 'tb', 'bcrt')
        i = 0
        while i < len(hrp_body) and hrp_body[i].isalpha():
            i += 1

        amount_part = hrp_body[i:]  # es: '300n', '10.5u', '', ...

        # amountless invoice (nessun importo nell'HRP) -> None
        if not amount_part:
            return None

        # separa suffisso se ultimo char è in munp
        if amount_part[-1] in "munp":
            suf = amount_part[-1]
            num_str = amount_part[:-1]
        else:
            suf = ""
            num_str = amount_part

        if not num_str:
            return None

        from decimal import Decimal
        val = Decimal(num_str)  # può essere decimale

        # 1 BTC = 100_000_000 sat = 100_000_000_000 msat
        if   suf == "m": msat = val * Decimal(100_000_000)       # mBTC → msat
        elif suf == "u": msat = val * Decimal(100_000)           # μBTC → msat
        elif suf == "n": msat = val * Decimal(100)               # nBTC → msat
        elif suf == "p": msat =  val / Decimal(10)               # pBTC → msat
        else:            msat = val * Decimal(100_000_000_000)   # BTC → msat

        return int(msat)  # floor
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
    Ordine di estrazione importo:
      1) tag 'amount' sul receipt (msat)
      2) tag 'bolt11' sul receipt (→ msat)
      3) 'description.tags' può contenere ['amount','<msat>']
    """
    res = {"sats":0, "unknown":True, "zapper_hex":None, "note_id":None,
           "recipients_in_desc":[], "recipients_in_event":[], "relays":[]}

    # 1) 'amount' (msat) sul receipt
    amt = parse_tag_list(ev, "amount")
    if amt:
        try:
            res["sats"] = int(amt[0]) // 1000
            res["unknown"] = False
        except:
            pass

    # 2) 'bolt11' sul receipt → msat
    if res["unknown"] or res["sats"] == 0:
        bolt = parse_tag_list(ev, "bolt11")
        if bolt:
            ms = msat_from_bolt11(bolt[0])
            # DEBUG: stampa cosa abbiamo parsato
            try:
                print(f"DEBUG bolt11 parse → msat={ms} (bolt11={bolt[0][:24]}…)")
            except Exception:
                pass
            if ms:
                res["sats"] = ms // 1000
                res["unknown"] = False

    # 3) description JSON (zap request) — tags e amount in msat
    desc = parse_tag_list(ev, "description")
    if desc:
        try:
            dj = json.loads(desc[0])
            if isinstance(dj, dict):
                res["zapper_hex"] = dj.get("pubkey") or res["zapper_hex"]
                tags = dj.get("tags") or []
                for tg in tags:
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
                                ms = int(str(tg[1]).strip())
                                # DEBUG: amount in description.tags
                                try:
                                    print(f"DEBUG desc.tags amount → msat={ms}")
                                except Exception:
                                    pass
                                if (res["unknown"] or res["sats"] == 0) and ms > 0:
                                    res["sats"] = ms // 1000
                                    res["unknown"] = False
                            except:
                                pass
        except Exception:
            pass

    # destinatari sull'evento (p/P)
    res["recipients_in_event"] = parse_tag_list(ev, "p") + parse_tag_list(ev, "P")

    # fallback diretti
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

