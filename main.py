import asyncio
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.enums import ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, ADMIN_IDS
from database import (
    init_db, WAVES_DATA, get_wave_slots, get_user_reservations_count, get_user_max_limit,
    toggle_slot, set_setting, get_setting, reset_all_slots, admin_force_free_slot,
    get_slot_by_index, add_user_extra_slots, admin_assign_slot
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class AdminStates(StatesGroup):
    waiting_for_custom_user = State()


async def is_admin(user_id: int, chat_id: int = None) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if chat_id and chat_id < 0:  # Группа / Форум
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                return True
        except Exception:
            pass
    return False


def build_grid_text(wave_id: int, user_count: int, max_limit: int, slots: list, username: str) -> str:
    wave_info = WAVES_DATA[wave_id]

    text = f"⚔️ <b>СЕТКА ОТКАТОВ БОССОВ</b>\n"
    text += f"👤 <b>Ваш аккаунт:</b> @{username}\n"
    text += f"📊 <b>Ваши брони:</b> <code>{user_count} / {max_limit}</code>\n\n"
    
    text += f"📌 <b>Как записаться:</b>\n"
    text += f"1️⃣ <b>Выбери волну</b> (кнопки В1–В4 внизу).\n"
    text += f"2️⃣ <b>Выбери свободный топ.</b> Цифра выбора на кнопке соответствует номеру строки в таблице ниже.\n"
    text += f"═════════════════════════════════════\n"
    text += f"🌊 <b>{wave_info['title']}</b>\n\n"

    text += "<pre>"
    for idx, slot in enumerate(slots):
        num = f"{idx + 1:>2}."
        user_raw = slot["username"] if slot["username"] else "🟢 Свободно"
        
        user_str = f"{user_raw:<18}"
        top1_str = f"{slot['top1_boss']:<17}"
        top2_str = f"{slot['top2_boss']}"

        text += f"{num} {user_str} │ {top1_str} │ {top2_str}\n"
    text += "</pre>"

    return text


def build_grid_keyboard(active_wave: int, slots: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    wave_buttons = []
    for w in range(1, 5):
        label = f"🔘 В{w}" if w == active_wave else f"В{w}"
        wave_buttons.append(InlineKeyboardButton(text=label, callback_data=f"wave:{w}"))
    builder.row(*wave_buttons)

    buttons = []
    for idx, slot in enumerate(slots):
        if slot["username"]:
            btn_text = f"{idx + 1}. 👤 {slot['username']}"
        else:
            btn_text = f"{idx + 1}. 🟢 Свободно"
        buttons.append(InlineKeyboardButton(text=btn_text, callback_data=f"slot:{active_wave}:{idx}"))

    for i in range(0, len(buttons), 2):
        builder.row(buttons[i], buttons[i+1])

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"wave:{active_wave}"),
        InlineKeyboardButton(text="🧹 Сбросить все (Админ)", callback_data="admin_reset")
    )

    return builder.as_markup()


async def update_dashboard_if_exists():
    chat_id = await get_setting("dashboard_chat_id")
    msg_id = await get_setting("dashboard_message_id")
    if chat_id and msg_id:
        try:
            full_text = "📊 <b>ДАШБОРД ОТКАТОВ БОССОВ</b>\n"
            full_text += "═════════════════════════════════════\n\n"

            for w in range(1, 5):
                slots = await get_wave_slots(w)
                wave_info = WAVES_DATA[w]
                
                full_text += f"🌊 <b>{wave_info['title']}</b>\n"
                full_text += "<pre>"

                for idx, slot in enumerate(slots):
                    num = f"{idx + 1:>2}."
                    user_raw = slot["username"] if slot["username"] else "🟢 Свободно"
                    
                    user_str = f"{user_raw:<18}"
                    top1_str = f"{slot['top1_boss']:<17}"
                    top2_str = f"{slot['top2_boss']}"

                    full_text += f"{num} {user_str} │ {top1_str} │ {top2_str}\n"

                full_text += "</pre>\n"

            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(msg_id),
                text=full_text,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка обновления дашборда: {e}")


@dp.message(Command("start", "grid"))
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


@dp.message(Command("bonus"))
async def cmd_bonus(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id, message.chat.id):
        await message.answer(
            f"⚠️ <b>У вас нет прав администратора.</b>\n"
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>",
            parse_mode="HTML"
        )
        return

    if not command.args:
        await message.answer("Формат команды: <code>/bonus @username 1</code>", parse_mode="HTML")
        return

    args = command.args.split()
    target_user = args[0]
    amount = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1

    new_limit = await add_user_extra_slots(target_user, amount)
    await message.answer(f"✅ Пользователю <b>{target_user}</b> добавлено +{amount} броней на эту неделю. Новый лимит: <b>{new_limit}</b>", parse_mode="HTML")


@dp.message(Command("setup_dashboard"))
async def cmd_setup_dashboard(message: types.Message):
    if not await is_admin(message.from_user.id, message.chat.id):
        await message.answer(
            f"⚠️ <b>Недостаточно прав.</b>\n"
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n\n"
            f"<i>Добавьте этот ID в ADMIN_IDS в config.py или назначьте администратором группы.</i>",
            parse_mode="HTML"
        )
        return

    msg = await message.answer("📊 Инициализация Дашборда...")
    await set_setting("dashboard_chat_id", str(message.chat.id))
    await set_setting("dashboard_message_id", str(msg.message_id))
    try:
        await bot.pin_chat_message(message.chat.id, msg.message_id)
    except Exception:
        pass
    await update_dashboard_if_exists()


@dp.callback_query(F.data.startswith("wave:"))
async def cb_switch_wave(callback: types.CallbackQuery, state: FSMContext):
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
async def cb_slot_click(callback: types.CallbackQuery, state: FSMContext):
    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id = int(wave_id_str)
    row_index = int(row_idx_str)
    
    user = callback.from_user
    username = user.username or user.first_name
    admin_flag = await is_admin(user.id, callback.message.chat.id)

    slot = await get_slot_by_index(wave_id, row_index)
    is_occupied = bool(slot["username"] or slot["user_id"])

    # 1. АДМИН кликает по СВОБОДНОМУ слоту
    if admin_flag and not is_occupied:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="👤 На себя", callback_data=f"adm_book_self:{wave_id}:{row_index}"),
            InlineKeyboardButton(text="✏️ Записать другого", callback_data=f"adm_book_other:{wave_id}:{row_index}")
        )
        builder.row(InlineKeyboardButton(text="◀️ Назад в сетку", callback_data=f"wave:{wave_id}"))

        await callback.message.edit_text(
            f"⚙️ <b>СЛОТ #{row_index + 1} (Свободен)</b>\n"
            f"Боссы: <i>{slot['top1_boss']} │ {slot['top2_boss']}</i>\n\n"
            f"Забронировать на себя или записать другого игрока?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # 2. АДМИН кликает по ЗАНЯТОМУ слоту
    if admin_flag and is_occupied:
        target_user = slot["username"] or f"ID:{slot['user_id']}"
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=f"📢 Тэгнуть гонщика {target_user}", callback_data=f"adm_tag:{wave_id}:{row_index}"))
        builder.row(InlineKeyboardButton(text=f"❌ Освободить слот #{row_index + 1}", callback_data=f"adm_free:{wave_id}:{row_index}"))
        builder.row(InlineKeyboardButton(text=f"➕ Начислить +1 бронь игроку {target_user}", callback_data=f"adm_add_bonus:{wave_id}:{target_user}"))
        builder.row(InlineKeyboardButton(text="◀️ Назад в сетку", callback_data=f"wave:{wave_id}"))

        await callback.message.edit_text(
            f"⚙️ <b>АДМИН-МЕНЮ УПРАВЛЕНИЯ СЛОТОМ #{row_index + 1}</b>\n\n"
            f"Занят игроком: <b>{target_user}</b>\n"
            f"Боссы: <i>{slot['top1_boss']} │ {slot['top2_boss']}</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # 3. ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ кликает по слоту
    success, msg, _ = await toggle_slot(wave_id, row_index, user.id, username)
    await callback.answer(msg, show_alert=True)

    if success:
        max_limit = await get_user_max_limit(username)
        count = await get_user_reservations_count(user.id, username)
        slots = await get_wave_slots(wave_id)

        text = build_grid_text(wave_id, count, max_limit, slots, username)
        reply_markup = build_grid_keyboard(wave_id, slots)

        try:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass
        
        await update_dashboard_if_exists()


@dp.callback_query(F.data.startswith("adm_book_self:"))
async def cb_adm_book_self(callback: types.CallbackQuery):
    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id, row_index = int(wave_id_str), int(row_idx_str)
    user = callback.from_user
    username = user.username or user.first_name

    success, msg, _ = await toggle_slot(wave_id, row_index, user.id, username)
    await callback.answer(msg, show_alert=True)

    max_limit = await get_user_max_limit(username)
    count = await get_user_reservations_count(user.id, username)
    slots = await get_wave_slots(wave_id)

    text = build_grid_text(wave_id, count, max_limit, slots, username)
    reply_markup = build_grid_keyboard(wave_id, slots)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass

    await update_dashboard_if_exists()


@dp.callback_query(F.data.startswith("adm_book_other:"))
async def cb_adm_book_other(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id, callback.message.chat.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id, row_index = int(wave_id_str), int(row_idx_str)

    await state.set_state(AdminStates.waiting_for_custom_user)
    await state.update_data(wave_id=wave_id, row_index=row_index)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data=f"wave:{wave_id}"))

    await callback.message.edit_text(
        f"✏️ <b>Введите имя / хэштег / @username</b> для записи в слот #{row_index + 1} (Волна {wave_id}):\n\n"
        f"<i>Просто отправьте текстовое сообщение в чат бота (например: <code>@Rodion_444</code> или <code>Frozi</code>)</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_custom_user)
async def process_custom_user_input(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id, message.chat.id):
        await state.clear()
        return

    data = await state.get_data()
    wave_id = data.get("wave_id")
    row_index = data.get("row_index")

    input_text = message.text.strip()
    await admin_assign_slot(wave_id, row_index, input_text)
    await state.clear()

    await message.answer(f"✅ В слот #{row_index + 1} (Волна {wave_id}) успешно записан: <b>{input_text}</b>", parse_mode="HTML")

    await update_dashboard_if_exists()


@dp.callback_query(F.data.startswith("adm_tag:"))
async def cb_adm_tag(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.message.chat.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parts = callback.data.split(":")
    wave_id = int(parts[1])
    row_index = int(parts[2])

    slot = await get_slot_by_index(wave_id, row_index)
    target_user = slot["username"] if slot else None

    if not target_user or target_user == "🟢 Свободно":
        await callback.answer("В этом слоте нет гонщика для тэга!", show_alert=True)
        return

    tag_text = (
        f"📢 {target_user}, вам напоминание по откату боссов!\n"
        f"🌊 <b>Волна {wave_id}</b> (Слот #{row_index + 1})\n"
        f"🥊 Боссы: <i>{slot['top1_boss']} │ {slot['top2_boss']}</i>"
    )

    thread_id = callback.message.message_thread_id if callback.message.is_topic_message else None

    await bot.send_message(
        chat_id=callback.message.chat.id,
        text=tag_text,
        message_thread_id=thread_id,
        parse_mode="HTML"
    )

    await callback.answer(f"Гонщик {target_user} отэгнут в чате!", show_alert=True)


@dp.callback_query(F.data.startswith("adm_free:"))
async def cb_adm_free(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.message.chat.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id, row_index = int(wave_id_str), int(row_idx_str)

    await admin_force_free_slot(wave_id, row_index)
    await callback.answer("Слот успешно освобожден!", show_alert=True)

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

    await update_dashboard_if_exists()


@dp.callback_query(F.data.startswith("adm_add_bonus:"))
async def cb_adm_add_bonus(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.message.chat.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parts = callback.data.split(":")
    wave_id = int(parts[1])
    target_user = parts[2]

    new_limit = await add_user_extra_slots(target_user, 1)
    await callback.answer(f"Игроку {target_user} добавлена 1 бронь на эту неделю! Лимит: {new_limit}", show_alert=True)

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


@dp.callback_query(F.data == "admin_reset")
async def cb_admin_reset(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if not await is_admin(callback.from_user.id, callback.message.chat.id):
        await callback.answer(f"⚠️ Сбросить сетку может только Администратор! Ваш ID: {callback.from_user.id}", show_alert=True)
        return

    await reset_all_slots()
    await callback.answer("Все слоты успешно очищены!", show_alert=True)

    user = callback.from_user
    username = user.username or user.first_name
    max_limit = await get_user_max_limit(username)
    count = await get_user_reservations_count(user.id, username)
    slots = await get_wave_slots(1)

    text = build_grid_text(1, count, max_limit, slots, username)
    reply_markup = build_grid_keyboard(1, slots)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass

    await update_dashboard_if_exists()


async def set_bot_commands(bot_instance: Bot):
    commands = [
        BotCommand(command="start", description="⚔️ Открыть сетку откатов"),
        BotCommand(command="setup_dashboard", description="📊 Закрепить дашборд в группе"),
        BotCommand(command="bonus", description="➕ Выдать доп. бронь (@username)")
    ]
    await bot_instance.set_my_commands(commands)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await set_bot_commands(bot)
    polling_task = asyncio.create_task(dp.start_polling(bot))
    yield
    polling_task.cancel()
    await bot.session.close()

@dp.message(Command("start", "grid"))  # Это уже есть в коде
...

# --- ДОБАВЬТЕ ЭТОТ БЛОК ДЛЯ CRON-JOB ---
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Bot is alive!"}
# --------------------------------------

app = FastAPI(lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
