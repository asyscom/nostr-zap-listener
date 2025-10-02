#!/usr/bin/env python3
import subprocess, time, json, sys
from datetime import datetime, timezone

SERVICE = "nostr-zap-listener.service"
THRESHOLD = 90  # secondi

def last_journal_ts(service):
    try:
        p = subprocess.run(
            ["journalctl", "-u", service, "-n", "1", "-o", "json", "--no-pager"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, text=True
        )
        out = p.stdout.strip()
        if not out:
            return None
        obj = json.loads(out)
        ts_us = obj.get("__REALTIME_TIMESTAMP")  # microsecondi come string
        if not ts_us:
            return None
        return int(ts_us) // 1000000  # convert to seconds epoch
    except Exception:
        return None

def restart_service(service):
    subprocess.run(["/bin/systemctl", "restart", service])

def log(msg):
    ts = datetime.now(timezone.utc).astimezone().isoformat()
    # syslog via logger
    subprocess.run(["logger", "-t", "nostr_watchdog", f"{ts} {msg}"])

def main():
    ts = last_journal_ts(SERVICE)
    now = int(time.time())
    if ts is None:
        log(f"No journal entry found for {SERVICE}, restarting as precaution")
        restart_service(SERVICE)
        return 0
    age = now - ts
    if age > THRESHOLD:
        log(f"Journal stale: last entry {age}s ago (> {THRESHOLD}s). Restarting {SERVICE}")
        restart_service(SERVICE)
    else:
        # optionally log only when debug needed
        pass
    return 0

if __name__=="__main__":
    sys.exit(main())

