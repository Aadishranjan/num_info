# Number-to-info Telegram bot

This bot is restricted to Telegram IDs listed in `TELEGRAM_ADMIN_IDS`. Aadhaar values are masked in every response and are never logged.

## Setup

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and add Telegram credentials, admin IDs, and the two API URLs.
3. Confirm that your APIs accept `number` and `aadhar` query parameters, or update those two request lines in `bot.py` to match the documented contract.
4. Run `python bot.py`.

Do not put API keys or real member data in source files, screenshots, tests, or issue reports.