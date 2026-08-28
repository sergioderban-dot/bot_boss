import os
from dotenv import load_dotenv

load_dotenv()

# Боевой токен бота:
BOT_TOKEN = os.getenv("BOT_TOKEN", "8006221091:AAFFRdzBreTE3OE3ZMpcWnMeYIoTcR3CWVo")

# ID администраторов:
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "548192041,262596215").split(",") if x.strip().isdigit()
]

# Основная боевая база данных:
DATABASE_NAME = "bosses.db"
