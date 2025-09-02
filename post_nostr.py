#!/usr/bin/env python3
import os, sys, time
from datetime import datetime, UTC
from dotenv import load_dotenv

from nostr.key import PrivateKey
from nostr.event import Event
from nostr.relay_manager import RelayManager

# --- Carica variabili da .env (NSEC, RELAYS opzionale) ---
load_dotenv()
NSEC = os.getenv("NSEC")

# Se RELAYS non è definita in .env, usa questa lista di default (includo tutti quelli richiesti)
DEFAULT_RELAYS = [
    "wss://relay.davidebtc.me",
    "wss://nos.lol",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.hifish.org",
    "wss://nostr.0x7e.xyz",
    "wss://nostr.massmux.com",
    "wss://relay.damus.io",
    "wss://relay.nostrplebs.com",
    "wss://relay.primal.net",
]
RELAYS = [r.strip() for r in (os.getenv("RELAYS") or "").split(",") if r.strip()] or DEFAULT_RELAYS

if not NSEC:
    print("ERROR: variabile NSEC mancante (impostala in .env).")
    sys.exit(1)

# --- Chiavi ---
sk = PrivateKey.from_nsec(NSEC)
pk = sk.public_key

# --- Contenuto promo (IT) ---
# Se preferisci, puoi aggiungere data/ora al post con la riga now sotto.
now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S %Z")
content = f"""⚡ Promo del mese

Zappa questa nota con 25.000 sats e avrai 1 anno di abbonamento “comp” al mio Substack (valore €50):
https://davidebtc186.substack.com/

✅ Solo 1 posto al mese — first come, first served.
👉 Dopo il pagamento, scrivimi in DM la tua email per attivare la comp.

({now})
Grazie per supportare il mio lavoro su Bitcoin, privacy e self-sovereignty!
#promo #substack #bitcoin
"""

# --- Crea & firma evento (API della libreria 'nostr' che stai usando) ---
event = Event(pk.hex(), content)  # (pubkey_hex, content)
sk.sign_event(event)              # firma corretta per questa libreria

print(f"npub: {pk.bech32()}")
print(f"Event ID (pre-publish): {event.id}")

# --- Pubblica sui relay ---
rm = RelayManager()
for url in RELAYS:
    rm.add_relay(url)

rm.open_connections()
time.sleep(1.5)  # breve attesa per stabilire le connessioni

rm.publish_event(event)
time.sleep(2.0)  # lascia il tempo di inviare

# Log semplice (senza accedere a proprietà non presenti)
print("Relays used:")
for url in RELAYS:
    print(f"- {url}: sent")

rm.close_connections()
print("Done.")

