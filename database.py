import aiosqlite
from datetime import datetime
from config import DATABASE_NAME

# Единый динамический пул локаций (10 боссов)
LOCATIONS = [
    "Немалая смелость",
    "Хозяин зеркал",
    "Шайтан-звезда",
    "Город зеленых книг",
    "Ведьмин дом",
    "Ночь в октябре",
    "Зимняя сказка",
    "Река чародеев",
    "Старый лес",
    "Фермерский домик"
]

LOCATIONS_EMOJI = {
    "Немалая смелость": "🦁",
    "Хозяин зеркал": "🪞",
    "Шайтан-звезда": "🌠",
    "Город зеленых книг": "📚",
    "Ведьмин дом": "🏚",
    "Ночь в октябре": "🎃",
    "Зимняя сказка": "❄️",
    "Река чародеев": "🌊",
    "Старый лес": "🌲",
    "Фермерский домик": "🏡"
}

WAVES_DATA = {
    1: {"title": "1 ВОЛНА Понедельник - Вторник. Закрытие: Вторник с 19:00 до 21:00 (МСК)"},
    2: {"title": "2 ВОЛНА Среда. Закрытие: Четверг с 12:00 до 14:00 (МСК)"},
    3: {"title": "3 ВОЛНА Четверг - Пятница. Закрытие: Пятница с 19:00 до 21:00 (МСК)"},
    4: {"title": "4 ВОЛНА Суббота. Закрытие: Суббота с 21:00 до 23:00 (МСК)"}
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
    """Автоматический сброс доп. бонусов при наступлении новой недели (воскресенье 00:00)"""
    current_week_key = datetime.now().strftime("%Y_%U")
    
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

        # Инициализация 40 пустых слотов (4 волны × 10 строк) со значениями NULL
        async with db.execute("SELECT COUNT(*) FROM slots") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                for wave_id in range(1, 5):
                    for idx in range(10):
                        await db.execute(
                            """INSERT INTO slots 
                               (wave_id, row_index, top1_boss, top2_boss, user_id, username) 
                               VALUES (?, ?, NULL, NULL, NULL, NULL)""",
                            (wave_id, idx)
                        )
                await db.commit()

    await check_and_apply_weekly_reset()

async def get_taken_bosses(wave_id: int, position: str) -> list:
    """Ищет занятые локации строго в одной указанной колонке (top1_boss или top2_boss)"""
    col = "top1_boss" if position == "top1" else "top2_boss"
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.execute(f"SELECT {col} FROM slots WHERE wave_id = ? AND {col} IS NOT NULL", (wave_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

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

async def reserve_slot_with_bosses(wave_id: int, row_index: int, user_id: int, username: str, top1: str, top2: str):
    """Запись пользователя в слот с выбранными боссами ТОП-1 и ТОП-2"""
    await check_and_apply_weekly_reset()
    uname = f"@{username}" if username and not username.startswith("@") else (username or "Игрок")

    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? AND row_index = ?", (wave_id, row_index)
        ) as cursor:
            slot = await cursor.fetchone()

        if not slot:
            return False, "Слот не найден"

        if slot["username"] or slot["user_id"]:
            return False, f"Слот уже занят игроком {slot['username']}"

        # Проверка лимита броней
        max_limit = await get_user_max_limit(uname)
        count = await get_user_reservations_count(user_id, uname)
        if count >= max_limit:
            return False, f"У вас уже {count}/{max_limit} броней!"

        # Проверка дубликатов занятых боссов в этой же волне по соответствующим колонкам
        taken_top1 = await get_taken_bosses(wave_id, "top1")
        taken_top2 = await get_taken_bosses(wave_id, "top2")

        if top1 in taken_top1:
            return False, f"Босс «{top1}» уже занят в ТОП-1 другом сокланом!"
        if top2 in taken_top2:
            return False, f"Босс «{top2}» уже занят в ТОП-2 другом сокланом!"

        await db.execute(
            """UPDATE slots 
               SET user_id = ?, username = ?, top1_boss = ?, top2_boss = ? 
               WHERE id = ?""",
            (user_id, uname, top1, top2, slot["id"])
        )
        await db.commit()
        
        top1_emoji = LOCATIONS_EMOJI.get(top1, "")
        top2_emoji = LOCATIONS_EMOJI.get(top2, "")
        return True, f"Вы успешно записаны!\nТОП-1: {top1_emoji} {top1}\nТОП-2: {top2_emoji} {top2}"

async def release_slot(wave_id: int, row_index: int, user_id: int, username: str):
    """Отмена брони и очистка выбранных боссов"""
    uname = f"@{username}" if username and not username.startswith("@") else (username or "Игрок")
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? AND row_index = ?", (wave_id, row_index)
        ) as cursor:
            slot = await cursor.fetchone()

        if not slot:
            return False, "Слот не найден"

        if slot["user_id"] == user_id or (slot["username"] and slot["username"].lower() == uname.lower()):
            await db.execute(
                """UPDATE slots 
                   SET user_id = NULL, username = NULL, top1_boss = NULL, top2_boss = NULL 
                   WHERE id = ?""", 
                (slot["id"],)
            )
            await db.commit()
            return True, "Запись отменена (слот освобожден)"
        return False, "Вы не можете отменить чужую запись"

async def admin_assign_slot(wave_id: int, row_index: int, username_text: str, top1: str = "Немалая смелость", top2: str = "Хозяин зеркал"):
    """Принудительная запись администратором"""
    uname = username_text.strip()
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            """UPDATE slots 
               SET user_id = NULL, username = ?, top1_boss = ?, top2_boss = ? 
               WHERE wave_id = ? AND row_index = ?""",
            (uname, top1, top2, wave_id, row_index)
        )
        await db.commit()

async def admin_force_free_slot(wave_id: int, row_index: int):
    """Принудительное освобождение слота администратором"""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            """UPDATE slots 
               SET user_id = NULL, username = NULL, top1_boss = NULL, top2_boss = NULL 
               WHERE wave_id = ? AND row_index = ?""",
            (wave_id, row_index)
        )
        await db.commit()

async def reset_all_slots():
    """Полный сброс всех 40 слотов"""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE slots SET user_id = NULL, username = NULL, top1_boss = NULL, top2_boss = NULL"
        )
        await db.commit()
