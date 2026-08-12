import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8006221091:AAGxiAgFaVxwrAk06QgXKZ-CyspFHerL9ac")
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "548192041").split(",") if x.strip().isdigit()
]
DATABASE_NAME = "bosses.db"
