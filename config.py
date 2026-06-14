import os

class Config:
     BOT_TOKEN: str  = os.getenv("BOT_TOKEN", "8261194661:AAFdto4jcpBgMh4YmG5zQfuWCK9DTW1WReI")
    API_ID:    int  = int(os.getenv("API_ID", "29687194"))
    API_HASH:  str  = os.getenv("API_HASH", "fb286056a72033e9870cacb170b31fcd")
    ADMIN_IDS: list = [
        int(x) for x in os.getenv("ADMIN_IDS", "1899208318").split(",") if x.strip().isdigit()
    ]
    DB_PATH:      str = os.getenv("DB_PATH", "broadcaster.db")
    SESSIONS_DIR: str = os.getenv("SESSIONS_DIR", "accounts")

    # Per-account defaults (overridable per account inside the bot)
    DEFAULT_GROUP_INTERVAL: int = 5    # seconds between each group
    DEFAULT_BATCH_INTERVAL: int = 300  # seconds to rest after one full cycle
