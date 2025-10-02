# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

[0.1.3] - 2025-10-02
Added
- Watchdog service (`nostr_watchdog.py`) with systemd `.service` and `.timer` to monitor and automatically restart the listener if it stops responding.
- Updates to README.md documenting the watchdog setup.
Fixed
- Ensured listener does not reply twice to the same zap after service restarts.
- Defensive handling of already-processed events in the database.

[0.1.2] - 2025-09-30
Added
- Pre-check in DB to skip already-processed zap events before replying.
- Minor logging improvements for debugging duplicate or unknown zaps.

[0.1.1] - 2025-09-04
Added
- MAX_SATS_PER_ZAP env to cap a single zap amount (in sats) to prevent inflated values (e.g., parsing mistakes).
- Extra debug logs to show which source determined the amount (receipt amount, bolt11 HRP, or description.tags["amount"]).
Fixed
- Clamp parsed sats to a safe range (>= 0 and <= MAX_SATS_PER_ZAP) to avoid accidental huge amounts.
- More defensive BOLT11 amount parsing (supports m/u/n/p suffixes and decimals; handles amountless invoices).
Docs
- README: document MAX_SATS_PER_ZAP and align DB_PATH default with code.

[0.1.0] - 2025-09-02
Added
- Initial public release: zap listener, robust amount parsing, thank-you replies.
- Weekly leaderboard script.
- .env.example, requirements.txt, README, MIT license.

