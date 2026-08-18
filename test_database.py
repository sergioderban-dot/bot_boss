import aiosqlite

TEST_DB_NAME = "test_bosses.db"

ALL_LOCATIONS = [
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

WAVES_INFO = {
    1: "1 ВОЛНА Понедельник - Вторник. Закрытие: Вторник с 19:00 до 21:00 (МСК)",
    2: "2 ВОЛНА Среда. Закрытие: Четверг с 12:00 до 14:00 (МСК)",
    3: "3 ВОЛНА Четверг - Пятница. Закрытие: Пятница с 19:00 до 21:00 (МСК)",
    4: "4 ВОЛНА Суббота. Закрытие: Суббота с 21:00 до 23:00 (МСК)"
}

async def init_test_db():
    async with aiosqlite.connect(TEST_DB_NAME) as db:
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
            CREATE TABLE IF NOT EXISTS user_limits (
                username TEXT PRIMARY KEY,
                extra_slots INTEGER DEFAULT 0
            )
        """)
        await db.commit()

        async with db.execute("SELECT COUNT(*) FROM slots") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                for wave_id in range(1, 5):
                    for idx in range(10):
                        await db.execute(
                            "INSERT INTO slots (wave_id, row_index, top1_boss, top2_boss, user_id, username) VALUES (?, ?, NULL, NULL, NULL, NULL)",
                            (wave_id, idx)
                        )
                await db.commit()

async def get_wave_slots(wave_id: int):
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? ORDER BY row_index ASC", (wave_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_slot(wave_id: int, row_index: int):
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slots WHERE wave_id = ? AND row_index = ?", (wave_id, row_index)
        ) as cursor:
            return await cursor.fetchone()

async def get_available_bosses(wave_id: int, position: str, exclude_boss: str = None):
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        col = "top1_boss" if position == "top1" else "top2_boss"
        async with db.execute(f"SELECT {col} FROM slots WHERE wave_id = ? AND {col} IS NOT NULL", (wave_id,)) as cursor:
            taken = [row[0] for row in await cursor.fetchall()]
        
        available = [loc for loc in ALL_LOCATIONS if loc not in taken]
        if exclude_boss and exclude_boss in available:
            available.remove(exclude_boss)
        return available

async def get_user_reservations_count(user_id: int, username: str) -> int:
    uname = f"@{username}" if username and not username.startswith("@") else username
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM slots WHERE user_id = ? OR (username IS NOT NULL AND LOWER(username) = LOWER(?))",
            (user_id, uname)
        ) as c:
            return (await c.fetchone())[0]

async def get_user_max_limit(username: str) -> int:
    uname = f"@{username}" if username and not username.startswith("@") else username
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        async with db.execute("SELECT extra_slots FROM user_limits WHERE LOWER(username) = LOWER(?)", (uname,)) as c:
            row = await c.fetchone()
            extra = row[0] if row else 0
            return 2 + extra

async def book_slot(wave_id: int, row_index: int, top1_boss: str, top2_boss: str, user_id: int, username: str):
    uname = f"@{username}" if username and not username.startswith("@") else username
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM slots WHERE wave_id = ? AND (top1_boss = ? OR top2_boss = ?)",
            (wave_id, top1_boss, top2_boss)
        ) as c:
            if (await c.fetchone())[0] > 0:
                return False, "Один из выбранных боссов уже занят кем-то другим!"

        await db.execute(
            """UPDATE slots 
               SET top1_boss = ?, top2_boss = ?, user_id = ?, username = ? 
               WHERE wave_id = ? AND row_index = ?""",
            (top1_boss, top2_boss, user_id, uname, wave_id, row_index)
        )
        await db.commit()
        return True, "Слот успешно забронирован!"

async def free_slot(wave_id: int, row_index: int):
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        await db.execute(
            "UPDATE slots SET top1_boss = NULL, top2_boss = NULL, user_id = NULL, username = NULL WHERE wave_id = ? AND row_index = ?",
            (wave_id, row_index)
        )
        await db.commit()

async def reset_all():
    async with aiosqlite.connect(TEST_DB_NAME) as db:
        await db.execute("UPDATE slots SET top1_boss = NULL, top2_boss = NULL, user_id = NULL, username = NULL")
        await db.commit()
