import os


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8261194661:AAFdto4jcpBgMh4YmG5zQfuWCK9DTW1WReI")
    API_ID = int(os.getenv("API_ID", "29687194"))
    API_HASH = os.getenv("API_HASH", "fb286056a72033e9870cacb170b31fcd")
    ADMIN_IDS = [
        int(x) for x in os.getenv("ADMIN_IDS", "1899208318").split(",") if x.strip().isdigit()
    ]
    DB_PATH = os.getenv("DB_PATH", "broadcaster.db")
    SESSIONS_DIR = os.getenv("SESSIONS_DIR", "accounts")

    DEFAULT_GROUP_INTERVAL = 5
    DEFAULT_BATCH_INTERVAL = 300
