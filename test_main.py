import os
import asyncio
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from test_database import (
    init_test_db, WAVES_INFO, get_wave_slots, get_slot, get_available_bosses,
    get_user_reservations_count, get_user_max_limit, book_slot, free_slot, reset_all
)

TEST_BOT_TOKEN = "7596426284:AAFEwlMiRR-nVHvB9g9mnlRnJ6gs1AFrmrc"
ADMIN_IDS = [548192041]

bot = Bot(token=TEST_BOT_TOKEN)
dp = Dispatcher()

class BookingWizard(StatesGroup):
    picking_top1 = State()
    picking_top2 = State()

def build_grid_text(wave_id: int, user_count: int, max_limit: int, slots: list, username: str) -> str:
    wave_title = WAVES_INFO[wave_id]

    text = f"⚔️ <b>ДИНАМИЧЕСКАЯ СЕТКА ОТКАТОВ (ТЕСТ)</b>\n"
    text += f"👤 <b>Ваш аккаунт:</b> @{username}\n"
    text += f"📊 <b>Ваши брони:</b> <code>{user_count} / {max_limit}</code>\n\n"
    text += f"📌 <b>Инструкция:</b>\n"
    text += f"1️⃣ Выберите волну (кнопки В1–В4 внизу).\n"
    text += f"2️⃣ Нажмите на свободный слот и соберите связку ТОП-1 и ТОП-2 боссов.\n"
    text += f"═════════════════════════════════════\n"
    text += f"🌊 <b>{wave_title}</b>\n\n"

    text += "<pre>"
    for idx, slot in enumerate(slots):
        num = f"{idx + 1:>2}."
        u = slot["username"] if slot["username"] else "🟢 Свободно"
        t1 = slot["top1_boss"] if slot["top1_boss"] else "—"
        t2 = slot["top2_boss"] if slot["top2_boss"] else "—"

        text += f"{num} {u:<16} │ {t1:<17} │ {t2}\n"
    text += "</pre>"
    return text

def build_grid_keyboard(active_wave: int, slots: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    wave_btns = [
        InlineKeyboardButton(text=f"🔘 В{w}" if w == active_wave else f"В{w}", callback_data=f"wave:{w}")
        for w in range(1, 5)
    ]
    builder.row(*wave_btns)

    slot_btns = []
    for idx, slot in enumerate(slots):
        btn_text = f"{idx + 1}. 👤 {slot['username']}" if slot["username"] else f"{idx + 1}. 🟢 Свободно"
        slot_btns.append(InlineKeyboardButton(text=btn_text, callback_data=f"slot:{active_wave}:{idx}"))

    for i in range(0, len(slot_btns), 2):
        builder.row(slot_btns[i], slot_btns[i+1])

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"wave:{active_wave}"),
        InlineKeyboardButton(text="🧹 Сбросить волны", callback_data="admin_reset")
    )
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = user.username or user.first_name

    max_limit = await get_user_max_limit(username)
    count = await get_user_reservations_count(user.id, username)
    slots = await get_wave_slots(1)

    text = build_grid_text(1, count, max_limit, slots, username)
    reply_markup = build_grid_keyboard(1, slots)
    await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("wave:"))
async def cb_wave(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    wave_id = int(callback.data.split(":")[1])
    user = callback.from_user
    username = user.username or user.first_name

    max_limit = await get_user_max_limit(username)
    count = await get_user_reservations_count(user.id, username)
    slots = await get_wave_slots(wave_id)

    text = build_grid_text(wave_id, count, max_limit, slots, username)
    reply_markup = build_grid_keyboard(wave_id, slots)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("slot:"))
async def cb_slot(callback: types.CallbackQuery, state: FSMContext):
    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id, row_index = int(wave_id_str), int(row_idx_str)
    user = callback.from_user
    username = user.username or user.first_name

    slot = await get_slot(wave_id, row_index)

    if slot["username"]:
        if slot["user_id"] == user.id or (slot["username"].lower() == f"@{username}".lower()) or user.id in ADMIN_IDS:
            await free_slot(wave_id, row_index)
            await callback.answer("Бронь снята, боссы возвращены в пул!", show_alert=True)
            
            slots = await get_wave_slots(wave_id)
            count = await get_user_reservations_count(user.id, username)
            max_limit = await get_user_max_limit(username)
            await callback.message.edit_text(
                build_grid_text(wave_id, count, max_limit, slots, username),
                reply_markup=build_grid_keyboard(wave_id, slots),
                parse_mode="HTML"
            )
            return
        else:
            await callback.answer(f"Слот занят игроком {slot['username']}", show_alert=True)
            return

    count = await get_user_reservations_count(user.id, username)
    max_limit = await get_user_max_limit(username)
    if count >= max_limit:
        await callback.answer(f"У вас уже максимум броней ({count}/{max_limit})!", show_alert=True)
        return

    available_top1 = await get_available_bosses(wave_id, position="top1")
    if not available_top1:
        await callback.answer("Все боссы ТОП-1 в этой волне уже разобраны!", show_alert=True)
        return

    await state.set_state(BookingWizard.picking_top1)
    await state.update_data(wave_id=wave_id, row_index=row_index)

    builder = InlineKeyboardBuilder()
    for boss in available_top1:
        builder.row(InlineKeyboardButton(text=f"🥊 {boss}", callback_data=f"pick_t1:{boss}"))
    builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data=f"wave:{wave_id}"))

    await callback.message.edit_text(
        f"🎯 <b>ШАГ 1/2: Выберите босса для ТОП-1</b>\n"
        f"Волна {wave_id} • Слот #{row_index + 1}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pick_t1:"))
async def cb_pick_t1(callback: types.CallbackQuery, state: FSMContext):
    chosen_top1 = callback.data.split("pick_t1:")[1]
    data = await state.get_data()
    wave_id = data["wave_id"]
    row_index = data["row_index"]

    await state.update_data(top1=chosen_top1)
    await state.set_state(BookingWizard.picking_top2)

    available_top2 = await get_available_bosses(wave_id, position="top2", exclude_boss=chosen_top1)

    builder = InlineKeyboardBuilder()
    for boss in available_top2:
        builder.row(InlineKeyboardButton(text=f"🛡️ {boss}", callback_data=f"pick_t2:{boss}"))
    builder.row(InlineKeyboardButton(text="◀️ Начать заново", callback_data=f"slot:{wave_id}:{row_index}"))

    await callback.message.edit_text(
        f"🎯 <b>ШАГ 2/2: Выберите босса для ТОП-2</b>\n"
        f"Волна {wave_id} • Слот #{row_index + 1}\n\n"
        f"Выбранный ТОП-1: <b>{chosen_top1}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pick_t2:"))
async def cb_pick_t2(callback: types.CallbackQuery, state: FSMContext):
    chosen_top2 = callback.data.split("pick_t2:")[1]
    data = await state.get_data()
    wave_id = data["wave_id"]
    row_index = data["row_index"]
    chosen_top1 = data["top1"]

    user = callback.from_user
    username = user.username or user.first_name

    success, msg = await book_slot(wave_id, row_index, chosen_top1, chosen_top2, user.id, username)
    await state.clear()
    await callback.answer(msg, show_alert=True)

    slots = await get_wave_slots(wave_id)
    count = await get_user_reservations_count(user.id, username)
    max_limit = await get_user_max_limit(username)

    await callback.message.edit_text(
        build_grid_text(wave_id, count, max_limit, slots, username),
        reply_markup=build_grid_keyboard(wave_id, slots),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_reset")
async def cb_reset(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Сброс доступен только администраторам!", show_alert=True)
        return

    await reset_all()
    await callback.answer("Сетка очищена!", show_alert=True)
    
    user = callback.from_user
    username = user.username or user.first_name
    slots = await get_wave_slots(1)
    await callback.message.edit_text(
        build_grid_text(1, 0, 2, slots, username),
        reply_markup=build_grid_keyboard(1, slots),
        parse_mode="HTML"
    )

async def set_bot_commands(bot_instance: Bot):
    commands = [
        BotCommand(command="start", description="⚔️ Открыть сетку откатов")
    ]
    await bot_instance.set_my_commands(commands)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_test_db()
    await set_bot_commands(bot)
    polling_task = asyncio.create_task(dp.start_polling(bot))
    yield
    polling_task.cancel()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Test Bot is alive!"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("test_main:app", host="0.0.0.0", port=port, reload=False)
