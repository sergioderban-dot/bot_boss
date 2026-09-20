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

from config import BOT_TOKEN, ADMIN_IDS, DATABASE_NAME
from database import (
    init_db, WAVES_DATA, LOCATIONS, LOCATIONS_EMOJI, get_wave_slots, get_user_reservations_count, get_user_max_limit,
    set_setting, get_setting, reset_all_slots, admin_force_free_slot,
    get_slot_by_index, add_user_extra_slots, admin_assign_slot, get_taken_bosses,
    reserve_slot_with_bosses, release_slot
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Состояния FSM для пошагового визарда выбора боссов
class SelectionWizard(StatesGroup):
    selecting_top1 = State()
    selecting_top2 = State()


# Состояние для приема текста/имени от админа
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
    text += f"1. Выбери волну с помощью кнопок В1, В2, В3, В4.\n"
    text += f"2. Чуть ниже выбери свободный слот (обозначен зелёным).\n"
    text += f"3. В появившемся списке сначала выбери Т1 босса, затем выбери Т2 босса.\n"
    text += f"═════════════════════════════════════\n"
    text += f"🌊 <b>{wave_info['title']}</b>\n\n"

    for idx, slot in enumerate(slots):
        num = idx + 1
        if slot["username"] or slot["user_id"]:
            user_raw = slot["username"] if slot["username"] else f"ID:{slot['user_id']}"
            top1_raw = slot["top1_boss"] if slot["top1_boss"] else "Не выбран"
            top2_raw = slot["top2_boss"] if slot["top2_boss"] else "Не выбран"
            
            t1_emoji = LOCATIONS_EMOJI.get(slot["top1_boss"], "")
            t2_emoji = LOCATIONS_EMOJI.get(slot["top2_boss"], "")
            
            top1_str = f"{t1_emoji} {top1_raw}".strip()
            top2_str = f"{t2_emoji} {top2_raw}".strip()

            text += f"<b>{num}. {user_raw}</b>\n  ├ 🥇 Т1: <i>{top1_str}</i>\n  └ 🥈 Т2: <i>{top2_str}</i>\n\n"
        else:
            text += f"<b>{num}. 🟢 Свободно</b>\n\n"

    return text


def build_grid_keyboard(active_wave: int, slots: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Переключение волн В1–В4
    wave_buttons = []
    for w in range(1, 5):
        label = f"🔘 В{w}" if w == active_wave else f"В{w}"
        wave_buttons.append(InlineKeyboardButton(text=label, callback_data=f"wave:{w}"))
    builder.row(*wave_buttons)

    # 10 кнопок строк слотов
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


def build_boss_keyboard(wave_id: int, taken_bosses: list, callback_prefix: str, exclude_boss: str = None) -> InlineKeyboardMarkup:
    """Генерация клавиатуры выбора боссов с изоляцией колонок ТОП-1 и ТОП-2"""
    builder = InlineKeyboardBuilder()
    buttons = []
    
    for boss in LOCATIONS:
        if boss == exclude_boss:
            buttons.append(InlineKeyboardButton(text=f"🚫 {boss} (Твой Т1)", callback_data="noop_selected"))
        elif boss in taken_bosses:
            buttons.append(InlineKeyboardButton(text=f"🔒 {boss} (Занято)", callback_data="noop_taken"))
        else:
            emoji = LOCATIONS_EMOJI.get(boss, "🟢")
            buttons.append(InlineKeyboardButton(text=f"{emoji} {boss}", callback_data=f"{callback_prefix}:{boss}"))

    for i in range(0, len(buttons), 2):
        builder.row(buttons[i], buttons[i+1])

    if callback_prefix == "wiz_top2":
        builder.row(InlineKeyboardButton(text="◀️ Назад к ТОП-1", callback_data="wiz_back_top1"))
    else:
        builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data=f"wave:{wave_id}"))

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
                
                full_text += f"🌊 <b>{wave_info['title']}</b>\n\n"

                for idx, slot in enumerate(slots):
                    num = idx + 1
                    if slot["username"] or slot["user_id"]:
                        user_raw = slot["username"] if slot["username"] else f"ID:{slot['user_id']}"
                        top1_raw = slot["top1_boss"] if slot["top1_boss"] else "Не выбран"
                        top2_raw = slot["top2_boss"] if slot["top2_boss"] else "Не выбран"
                        
                        t1_emoji = LOCATIONS_EMOJI.get(slot["top1_boss"], "")
                        t2_emoji = LOCATIONS_EMOJI.get(slot["top2_boss"], "")

                        top1_str = f"{t1_emoji} {top1_raw}".strip()
                        top2_str = f"{t2_emoji} {top2_raw}".strip()

                        full_text += f"<b>{num}. {user_raw}</b>\n  ├ 🥇 Т1: <i>{top1_str}</i>\n  └ 🥈 Т2: <i>{top2_str}</i>\n\n"
                    else:
                        full_text += f"<b>{num}. 🟢 Свободно</b>\n\n"

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
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>",
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


@dp.callback_query(F.data == "noop_taken")
async def cb_noop_taken(callback: types.CallbackQuery):
    await callback.answer("🔒 Этот босс уже забронирован другим сокланом в этой категории!", show_alert=True)


@dp.callback_query(F.data == "noop_selected")
async def cb_noop_selected(callback: types.CallbackQuery):
    await callback.answer("🚫 Этот босс уже выбран вами на шаге ТОП-1!", show_alert=True)


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

    # 1. Если слот ЗАНЯТ:
    if is_occupied:
        if admin_flag:
            target_user = slot["username"] or f"ID:{slot['user_id']}"
            t1_e = LOCATIONS_EMOJI.get(slot["top1_boss"], "")
            t2_e = LOCATIONS_EMOJI.get(slot["top2_boss"], "")
            top1_disp = f"{t1_e} {slot['top1_boss']}".strip() if slot["top1_boss"] else "Не указан"
            top2_disp = f"{t2_e} {slot['top2_boss']}".strip() if slot["top2_boss"] else "Не указан"

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text=f"📢 Тэгнуть гонщика {target_user}", callback_data=f"adm_tag:{wave_id}:{row_index}"))
            builder.row(InlineKeyboardButton(text=f"❌ Освободить слот #{row_index + 1}", callback_data=f"adm_free:{wave_id}:{row_index}"))
            builder.row(InlineKeyboardButton(text=f"➕ Начислить +1 бронь игроку {target_user}", callback_data=f"adm_add_bonus:{wave_id}:{target_user}"))
            builder.row(InlineKeyboardButton(text="◀️ Назад в сетку", callback_data=f"wave:{wave_id}"))

            await callback.message.edit_text(
                f"⚙️ <b>АДМИН-МЕНЮ УПРАВЛЕНИЯ СЛОТОМ #{row_index + 1}</b>\n\n"
                f"Занят игроком: <b>{target_user}</b>\n"
                f"Боссы: <i>{top1_disp} │ {top2_disp}</i>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        else:
            await callback.answer(f"Слот занят игроком {slot['username']}", show_alert=True)
            return

    # 2. Если слот СВОБОДЕН и нажимает АДМИН -> меню выбора (На себя / Записать другого)
    if admin_flag:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="👤 На себя", callback_data=f"adm_book_self:{wave_id}:{row_index}"),
            InlineKeyboardButton(text="✏️ Записать другого", callback_data=f"adm_book_other:{wave_id}:{row_index}")
        )
        builder.row(InlineKeyboardButton(text="◀️ Назад в сетку", callback_data=f"wave:{wave_id}"))

        await callback.message.edit_text(
            f"⚙️ <b>СЛОТ #{row_index + 1} (Свободен)</b>\n\n"
            f"Забронировать на себя (через выбор) или записать любого игрока?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # 3. Если слот СВОБОДЕН и нажимает ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ -> Запуск Визарда
    await start_wizard_top1(callback, state, wave_id, row_index)


# Запуск Шага 1 Визарда (Выбор ТОП-1)
async def start_wizard_top1(callback: types.CallbackQuery, state: FSMContext, wave_id: int, row_index: int):
    user = callback.from_user
    username = user.username or user.first_name
    
    # Проверка лимита броней
    max_limit = await get_user_max_limit(username)
    count = await get_user_reservations_count(user.id, username)
    if count >= max_limit:
        await callback.answer(f"У вас уже {count}/{max_limit} броней!", show_alert=True)
        return

    await state.set_state(SelectionWizard.selecting_top1)
    await state.update_data(wave_id=wave_id, row_index=row_index)

    taken_top1 = await get_taken_bosses(wave_id, "top1")
    reply_markup = build_boss_keyboard(wave_id, taken_top1, callback_prefix="wiz_top1")

    await callback.message.edit_text(
        f"⚔️ <b>ШАГ 1: ВЫБОР БОССА ТОП-1</b>\n"
        f"🌊 <b>Волна {wave_id}</b> (Слот #{row_index + 1})\n\n"
        f"👇 <i>Выберите первого доступного босса:</i>\n"
        f"🔒 — <i>боссы, уже забронированные в ТОП-1 этой волны</i>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("wiz_top1:"), SelectionWizard.selecting_top1)
async def cb_wiz_top1_select(callback: types.CallbackQuery, state: FSMContext):
    top1_boss = callback.data.split(":", 1)[1]
    data = await state.get_data()
    wave_id = data["wave_id"]
    row_index = data["row_index"]

    await state.update_data(top1_boss=top1_boss)
    await state.set_state(SelectionWizard.selecting_top2)

    taken_top2 = await get_taken_bosses(wave_id, "top2")
    reply_markup = build_boss_keyboard(wave_id, taken_top2, callback_prefix="wiz_top2", exclude_boss=top1_boss)

    top1_emoji = LOCATIONS_EMOJI.get(top1_boss, "")

    await callback.message.edit_text(
        f"⚔️ <b>ШАГ 2: ВЫБОР БОССА ТОП-2</b>\n"
        f"🌊 <b>Волна {wave_id}</b> (Слот #{row_index + 1})\n"
        f"1️⃣ <b>Выбран ТОП-1:</b> {top1_emoji} {top1_boss}\n\n"
        f"👇 <i>Теперь выберите второго доступного босса:</i>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "wiz_back_top1", SelectionWizard.selecting_top2)
async def cb_wiz_back_top1(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    wave_id = data["wave_id"]
    row_index = data["row_index"]
    await start_wizard_top1(callback, state, wave_id, row_index)


@dp.callback_query(F.data.startswith("wiz_top2:"), SelectionWizard.selecting_top2)
async def cb_wiz_top2_select(callback: types.CallbackQuery, state: FSMContext):
    top2_boss = callback.data.split(":", 1)[1]
    data = await state.get_data()
    wave_id = data["wave_id"]
    row_index = data["row_index"]
    top1_boss = data["top1_boss"]

    await state.clear()

    user = callback.from_user
    username = user.username or user.first_name

    success, msg = await reserve_slot_with_bosses(wave_id, row_index, user.id, username, top1_boss, top2_boss)
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


@dp.callback_query(F.data.startswith("adm_book_self:"))
async def cb_adm_book_self(callback: types.CallbackQuery, state: FSMContext):
    _, wave_id_str, row_idx_str = callback.data.split(":")
    wave_id, row_index = int(wave_id_str), int(row_idx_str)
    await start_wizard_top1(callback, state, wave_id, row_index)


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
        f"<i>Отправьте текстовое сообщение в чат бота (например: <code>@Rodion_444</code> или <code>Frozi</code>)</i>",
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

    t1_e = LOCATIONS_EMOJI.get(slot["top1_boss"], "")
    t2_e = LOCATIONS_EMOJI.get(slot["top2_boss"], "")
    top1_disp = f"{t1_e} {slot['top1_boss']}".strip() if slot["top1_boss"] else "Не указан"
    top2_disp = f"{t2_e} {slot['top2_boss']}".strip() if slot["top2_boss"] else "Не указан"

    tag_text = (
        f"📢 {target_user}, вам напоминание по откату боссов!\n"
        f"🌊 <b>Волна {wave_id}</b> (Слот #{row_index + 1})\n"
        f"🥊 Боссы: <i>{top1_disp} │ {top2_disp}</i>"
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
    
    # Принудительно отвязываем вебхук
    await bot.delete_webhook(drop_pending_updates=True)
    
    polling_task = asyncio.create_task(dp.start_polling(bot))
    yield
    polling_task.cancel()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)


# Эндпоинт FastAPI для health-check
@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Boss Bot Service",
        "database": DATABASE_NAME
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
