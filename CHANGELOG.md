# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.1.1] - 2025-09-04
### Added
- `MAX_SATS_PER_ZAP` env to cap a single zap amount (in sats) to prevent inflated values (e.g., parsing mistakes).
- Extra debug logs to show which source determined the amount (receipt `amount`, `bolt11` HRP, or `description.tags["amount"]`).

### Fixed
- Clamp parsed sats to a safe range (>= 0 and <= `MAX_SATS_PER_ZAP`) to avoid accidental huge amounts.
- More defensive BOLT11 amount parsing (supports `m/u/n/p` suffixes and decimals; handles amountless invoices).

### Docs
- README: document `MAX_SATS_PER_ZAP` and align `DB_PATH` default with code.

## [0.1.0] - 2025-09-02
### Added
- Initial public release: zap listener, robust amount parsing, thank-you replies.
- Weekly leaderboard script.
- `.env.example`, `requirements.txt`, README, MIT license.

