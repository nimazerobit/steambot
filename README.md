# Steam Bot
A Telegram bot for searching the Steam store, converting prices to toman, changing store regions, and managing a personal favorites list.

## Features
- Inline and `/search` Steam game search
- Region-aware Steam pricing with cached currency data
- Persian-formatted prices and timestamps
- Add, remove, and paginate favorites
- Wishlist reminders
- Required-channel membership checks
- Admin panel, user lookup, banning, and broadcasts

## Requirements
- Python 3.11+
- A Telegram bot token from
- A bot account with access to any required channels configured below

Install dependencies:
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration
Copy the example configuration and edit it:

Set `BOT_TOKEN`, `BOT_USERNAME`, `ADMINS`, `OWNERS`, `DB_PATH`, and `REQUIRED_CHATS` in `config/config.json`. The database path is resolved relative to the project root. Keep `config/config.json`, `bot.db`, and `config/currency_prices.json` out of version control.

## Run
```bash
python  main.py
```

## Commands
Users can use `/start`, `/menu`, `/search <game>`, `/favorites`, `/region`, and `/dev`.
Owners and admins additionally have `/users`, `/user <id|@username|hash>`, `/adminpanel`, and `/broadcast`.