# Data dictionary

Everything here is fictional except `documents/`, which is public-domain US federal rule text. The tables come from a
seeded generator that is not part of this folder, and `documents/` holds the rule texts as shipped; this recipe has no
script that regenerates either.

| File | Rows | Key | Columns |
|---|---|---|---|
| `assets.csv` | 36 | `asset_id` (the ticker) | `company_name`, `sic_code`, `sector` (SIC division), `industry`, `exchange`, `profile`, `first_session`, `last_session`, `sessions`, `median_dollar_volume`, `liquidity_rank` (1 = most liquid, unique), `is_synthetic` |
| `daily_prices.csv` | 5,976 | `price_id` = `asset_id-date`; unique (`asset_id`, `trading_date`) | `open`, `high`, `low`, `close`, `adjusted_close` (equal to `close`: no splits), `volume`, `dollar_volume`, `total_return_1d` (`close` / previous `close` - 1; 0.0 on the first session) |
| `trading_sessions.csv` | 166 | `session_id`, `trading_date` | `close_at` (21:00 UTC), `symbols` |
| `company_news.csv` | 484 | `news_id` | `primary_asset_id` -> assets, `published_at` (UTC), `source_name`, `headline`, `event_type`, `sentiment_label` (positive / neutral / negative) |
| `asset_relationships.csv` | 54 | `relationship_id` | `source_asset_id`, `target_asset_id` (both directions of each declared same-industry peer pair, so 27 pairs), `relationship_type`, `peer_rank` |

`documents/` holds three short rule texts and a `manifest.json` of their sources and hashes.

The file runs through 2026-08-31, five sessions after the prediction anchor of 2026-08-24.
