import aiosqlite
from datetime import datetime
from config import DATABASE_NAME

WAVES_DATA = {
    1: {
        "title": "1 ВОЛНА Понедельник - Вторник. Закрытие: Вторник с 19:00 до 21:00 (МСК)",
        "rows": [
            {"u": "@Toyota_TruenoAE86", "top1": "Немалая смелость", "top2": "Хозяин зеркал"},
            {"u": "@Yuzzzabr", "top1": "Шайтан-звезда", "top2": "Город зеленых книг"},
            {"u": "@sem_Abubakr", "top1": "Ведьмин дом", "top2": "Ночь в октябре"},
            {"u": "@jittoot", "top1": "Зимняя сказка", "top2": "Ведьмин дом"},
            {"u": "@danilchet", "top1": "Река чародеев", "top2": "Немалая смелость"},
            {"u": "@jittoot", "top1": "Старый лес", "top2": "Шайтан-звезда"},
            {"u": "@Vladislawes", "top1": "Хозяин зеркал", "top2": "Зимняя сказка"},
            {"u": "@darkhun733r", "top1": "Город зеленых книг", "top2": "Старый лес"},
            {"u": "@Rodion_444", "top1": "Ночь в октябре", "top2": "Фермерский домик"},
            {"u": "@FCSMNN152RUS", "top1": "Фермерский домик", "top2": "Река чародеев"}
        ]
    },
    2: {
        "title": "2 ВОЛНА Среда. Закрытие: Четверг с 12:00 до 14:00 (МСК)",
        "rows": [
            {"u": "Frozi", "top1": "Фермерский домик", "top2": "Шайтан-звезда"},
            {"u": "@Murazavr", "top1": "Хозяин зеркал", "top2": "Река чародеев"},
            {"u": "@invalid83", "top1": "Река чародеев", "top2": "Ночь в октябре"},
            {"u": "@TipokSergey", "top1": "Ночь в октябре", "top2": "Ведьмин дом"},
            {"u": "@nirehcep", "top1": "Немалая смелость", "top2": "Город зеленых книг"},
            {"u": "@darkhun733r", "top1": "Город зеленых книг", "top2": "Фермерский домик"},
            {"u": "@Rodion_444", "top1": "Шайтан-звезда", "top2": "Старый лес"},
            {"u": "@Vladislawes", "top1": "Зимняя сказка", "top2": "Хозяин зеркал"},
            {"u": "@sergioderban", "top1": "Старый лес", "top2": "Немалая смелость"},
            {"u": "@sergioderban", "top1": "Ведьмин дом", "top2": "Зимняя сказка"}
        ]
    },
    3: {
        "title": "3 ВОЛНА Четверг - Пятница. Закрытие: Пятница с 19:00 до 21:00 (МСК)",
        "rows": [
            {"u": "Артур Бро", "top1": "Немалая смелость", "top2": "Фермерский домик"},
            {"u": "@darkhun733r", "top1": "Зимняя сказка", "top2": "Хозяин зеркал"},
            {"u": "@invalid83", "top1": "Хозяин зеркал", "top2": "Ночь в октябре"},
            {"u": "@jittoot", "top1": "Фермерский домик", "top2": "Старый лес"},
            {"u": "@jittoot", "top1": "Ночь в октябре", "top2": "Зимняя сказка"},
            {"u": "@FCSMNN152RUS", "top1": "Старый лес", "top2": "Река чародеев"},
            {"u": "@nirehcep", "top1": "Город зеленых книг", "top2": "Немалая смелость"},
            {"u": "@sem_Abubakr", "top1": "Ведьмин дом", "top2": "Шайтан-звезда"},
            {"u": "@Yuzzzabr", "top1": "Шайтан-звезда", "top2": "Город зеленых книг"},
            {"u": "@danilchet", "top1": "Река чародеев", "top2": "Ведьмин дом"}
        ]
    },
    4: {
        "title": "4 ВОЛНА Суббота. Закрытие: Суббота с 21:00 до 23:00 (МСК)",
        "rows": [
            {"u": "@darkhun733r", "top1": "Ночь в октябре", "top2": "Старый лес"},
            {"u": "@Murazavr", "top1": "Зимняя сказка", "top2": "Город зеленых книг"},
            {"u": "@Toyota_TruenoAE86", "top1": "Хозяин зеркал", "top2": "Немалая смелость"},
            {"u": "@TipokSergey", "top1": "Фермерский домик", "top2": "Ведьмин дом"},
            {"u": "@sergioderban", "top1": "Река чародеев", "top2": "Зимняя сказка"},
            {"u": "@sergioderban", "top1": "Ведьмин дом", "top2": "Ночь в октябре"},
            {"u": None, "top1": "Немалая смелость", "top2": "Хозяин зеркал"},
            {"u": "Артур Бро", "top1": "Город зеленых книг", "top2": "Фермерский домик"},
            {"u": None, "top1": "Старый лес", "top2": "Шайтан-звезда"},
            {"u": "Frozi", "top1": "Шайтан-звезда", "top2": "Река чародеев"}
        ]
    }
}

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        await db.commit()

async def get_setting(key: str):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else None

async def check_and_apply_weekly_reset():
    year, week, _ = datetime.now().isocalendar()
    current_week_key = f"{year}_{week}"
    
    last_week_key = await get_setting("last_bonus_reset_week")
    if last_week_key != current_week_key:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            await db.execute("DELETE FROM user_limits")
            await db.commit()
        await set_setting("last_bonus_reset_week", current_week_key)

async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wave_id INTEGER,
                row_index INTEGER,
                top1_boss TEXT,
                top2_boss TEXT,
                user_id BIGINT,
                username TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_limits (
                username TEXT PRIMARY KEY,
                extra_slots INTEGER DEFAULT 0
            )
        """)
        await db.commit()

        async with db.execute("SELECT COUNT(*) FROM slots") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                for wave_id, wave_info in WAVES_DATA.items():
                    for idx, row in enumerate(wave_info["rows"]):
                        await db.execute(
                            """INSERT INTO slots 
                               (wave_id, row_index, top1_boss, top2_boss, username) 
                               VALUES (?, ?, ?, ?, ?)""",
                            (wave_id, idx, row["top1"], row["top2"], row["u"])
                        )
                await db.commit()

    await check_and_apply_weekly_reset()

async def get_wave_slots(wave_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? ORDER BY row_index ASC", (wave_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_slot_by_index(wave_id: int, row_index: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? AND row_index = ?", (wave_id, row_index)
        ) as cursor:
            return await cursor.fetchone()

async def get_user_max_limit(username: str) -> int:
    await check_and_apply_weekly_reset()
    uname = f"@{username}" if username and not username.startswith("@") else username
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.execute(
            "SELECT extra_slots FROM user_limits WHERE LOWER(username) = LOWER(?)", (uname,)
        ) as c:
            row = await c.fetchone()
            extra = row[0] if row else 0
            return 2 + extra

async def add_user_extra_slots(username: str, amount: int = 1) -> int:
    await check_and_apply_weekly_reset()
    uname = f"@{username}" if username and not username.startswith("@") else username
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            """INSERT INTO user_limits (username, extra_slots) VALUES (?, ?)
               ON CONFLICT(username) DO UPDATE SET extra_slots = extra_slots + ?""",
            (uname, amount, amount)
        )
        await db.commit()
    return await get_user_max_limit(uname)

async def get_user_reservations_count(user_id: int, username: str) -> int:
    async with aiosqlite.connect(DATABASE_NAME) as db:
        uname = f"@{username}" if username and not username.startswith("@") else username
        async with db.execute(
            "SELECT COUNT(*) FROM slots WHERE user_id = ? OR (username IS NOT NULL AND LOWER(username) = LOWER(?))",
            (user_id, uname)
        ) as c:
            return (await c.fetchone())[0]

async def toggle_slot(wave_id: int, row_index: int, user_id: int, username: str):
    await check_and_apply_weekly_reset()
    uname = f"@{username}" if username and not username.startswith("@") else (username or "Игрок")
    
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? AND row_index = ?",
            (wave_id, row_index)
        ) as cursor:
            slot = await cursor.fetchone()

        if not slot:
            return False, "Слот не найден", False

        if slot["user_id"] == user_id or (slot["username"] and slot["username"].lower() == uname.lower()):
            await db.execute(
                "UPDATE slots SET user_id = NULL, username = NULL WHERE id = ?", (slot["id"],)
            )
            await db.commit()
            return True, "Запись отменена (слот освобожден)", False

        if slot["username"] or slot["user_id"]:
            return False, f"Слот занят игроком {slot['username']}", True

        max_limit = await get_user_max_limit(uname)
        count = await get_user_reservations_count(user_id, uname)
        if count >= max_limit:
            return False, f"У вас уже {count}/{max_limit} броней!", False

        await db.execute(
            "UPDATE slots SET user_id = ?, username = ? WHERE id = ?", (user_id, uname, slot["id"])
        )
        await db.commit()
        return True, "Вы успешно записаны!", False

async def admin_assign_slot(wave_id: int, row_index: int, username_text: str):
    """Принудительная запись любого текста/хэштега админом"""
    uname = username_text.strip()
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE slots SET user_id = NULL, username = ? WHERE wave_id = ? AND row_index = ?",
            (uname, wave_id, row_index)
        )
        await db.commit()

async def admin_force_free_slot(wave_id: int, row_index: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE slots SET user_id = NULL, username = NULL WHERE wave_id = ? AND row_index = ?",
            (wave_id, row_index)
        )
        await db.commit()

async def reset_all_slots():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("UPDATE slots SET user_id = NULL, username = NULL")
        await db.commit()
