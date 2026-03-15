from aiogram import Router, F, Bot
from aiogram.types import (Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import OWNER_ID
from database import (
    get_user_by_telegram_id, set_user_role,
    create_cafe, update_cafe_location,
    get_all_cafes, get_all_admins, get_cafe_by_id, delete_cafe,
    get_cafe_admins, add_cafe_admin, remove_cafe_admin,
    MAX_ADMINS_PER_CAFE,
    add_channel, remove_channel, get_all_channels, get_channel_by_id
)
from models import Role, User as UserModel
from keyboards import location_kb, cancel_kb, cafes_inline_kb

router = Router()


# ── Klaviatura ────────────────────────────────────────────────────────────────

def owner_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Cafe qo'shish"), KeyboardButton(text="➕ Admin qo'shish")],
            [KeyboardButton(text="🔗 Admin biriktirish"), KeyboardButton(text="➖ Admin olish")],
            [KeyboardButton(text="🗑 Cafe o'chirish"), KeyboardButton(text="📊 Cafeler ro'yxati")],
            [KeyboardButton(text="📢 Guruh/Kanal xabari"), KeyboardButton(text="📋 Guruhlar ro'yxati")],
            [KeyboardButton(text="👤 User rejimi")],
        ],
        resize_keyboard=True
    )


# ── States ────────────────────────────────────────────────────────────────────

class CafeAdd(StatesGroup):
    name = State()
    location = State()

class AdminAdd(StatesGroup):
    phone = State()

class AssignAdmin(StatesGroup):
    pick_cafe = State()
    pick_admin = State()

class RemoveAdmin(StatesGroup):
    pick_cafe = State()
    pick_admin = State()

class Broadcast(StatesGroup):
    pick_targets = State()   # guruh tanlash
    write_message = State()  # xabar yozish
    confirm = State()        # tasdiqlash


def is_owner(msg: Message) -> bool:
    return msg.from_user.id == OWNER_ID


# ── Cafe qo'shish ─────────────────────────────────────────────────────────────

@router.message(F.text == "➕ Cafe qo'shish")
async def cafe_add_start(message: Message, state: FSMContext):
    if not is_owner(message):
        return
    await state.set_state(CafeAdd.name)
    await message.answer("Cafe nomini kiriting:", reply_markup=cancel_kb())


@router.message(CafeAdd.name)
async def cafe_add_name(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=owner_kb())
    await state.update_data(cafe_name=message.text.strip())
    await state.set_state(CafeAdd.location)
    await message.answer("📍 Cafe lokatsiyasini yuboring:", reply_markup=location_kb())


@router.message(CafeAdd.location, F.location)
async def cafe_add_location(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    cafe = await create_cafe(session, data["cafe_name"])
    await update_cafe_location(session, cafe.id, message.location.latitude, message.location.longitude)
    await state.clear()
    await message.answer(
        f"✅ <b>{cafe.name}</b> cafesi qo'shildi!\n\n"
        f"Admin biriktirish uchun '🔗 Admin biriktirish' tugmasini bosing.",
        parse_mode="HTML", reply_markup=owner_kb()
    )


# ── Admin qo'shish (foydalanuvchini admin qilish) ─────────────────────────────

@router.message(F.text == "➕ Admin qo'shish")
async def admin_add_start(message: Message, state: FSMContext):
    if not is_owner(message):
        return
    await state.set_state(AdminAdd.phone)
    await message.answer(
        "Admin qilmoqchi bo'lgan foydalanuvchining telefon raqamini kiriting:\n"
        "Masalan: +998901234567\n\n"
        "⚠️ Foydalanuvchi avval /start bosib telefon yuborgan bo'lishi kerak.",
        reply_markup=cancel_kb()
    )


@router.message(AdminAdd.phone)
async def admin_add_confirm(message: Message, state: FSMContext, session: AsyncSession):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=owner_kb())

    phone = message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    r = await session.execute(select(UserModel).where(UserModel.phone == phone))
    user = r.scalar_one_or_none()
    if not user:
        return await message.answer(
            "❌ Bu telefon raqamli foydalanuvchi topilmadi.\n"
            "Foydalanuvchi avval /start bosib telefon yuborishi kerak."
        )
    if user.role == Role.owner:
        return await message.answer("❌ Bu foydalanuvchi owner, admin qilib bo'lmaydi.")

    await set_user_role(session, user.telegram_id, Role.admin)
    await state.clear()
    await message.answer(
        f"✅ <b>{user.name}</b> ({phone}) admin bo'ldi!\n\n"
        f"Endi '🔗 Admin biriktirish' orqali cafega biriktiring.",
        parse_mode="HTML", reply_markup=owner_kb()
    )


# ── Admin biriktirish ─────────────────────────────────────────────────────────

@router.message(F.text == "🔗 Admin biriktirish")
async def assign_start(message: Message, state: FSMContext, session: AsyncSession):
    if not is_owner(message):
        return
    cafes = await get_all_cafes(session)
    if not cafes:
        return await message.answer("❌ Hozircha cafe yo'q. Avval cafe qo'shing.")
    admins = await get_all_admins(session)
    if not admins:
        return await message.answer("❌ Hozircha admin yo'q. Avval admin qo'shing.")

    await state.set_state(AssignAdmin.pick_cafe)
    await message.answer("☕ Qaysi cafega admin biriktirmoqchisiz?",
                         reply_markup=cafes_inline_kb(cafes, prefix="asgn_cafe"))


@router.callback_query(F.data.startswith("asgn_cafe:"))
async def assign_pick_cafe(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cafe_id = int(callback.data.split(":")[1])
    cafe = await get_cafe_by_id(session, cafe_id)
    current = await get_cafe_admins(session, cafe_id)
    all_admins = await get_all_admins(session)
    current_ids = {a.id for a in current}

    # Hozirgi adminlar matni
    cur_text = ""
    if current:
        names = ", ".join(a.name for a in current)
        cur_text = f"\n\n👥 Hozirgi adminlar ({len(current)}/{MAX_ADMINS_PER_CAFE}): {names}"

    if len(current) >= MAX_ADMINS_PER_CAFE:
        await callback.message.edit_text(
            f"☕ <b>{cafe.name}</b>{cur_text}\n\n"
            f"⚠️ Bu cafeda allaqachon {MAX_ADMINS_PER_CAFE} ta admin bor.\n"
            f"Yangi admin qo'shish uchun avval '➖ Admin olish' orqali birini olib tashlang.",
            parse_mode="HTML"
        )
        await state.clear()
        return await callback.answer()

    available = [a for a in all_admins if a.id not in current_ids]
    if not available:
        await callback.message.edit_text(
            f"☕ <b>{cafe.name}</b>{cur_text}\n\n"
            f"⚠️ Barcha adminlar allaqachon ushbu cafega biriktirilgan.",
            parse_mode="HTML"
        )
        await state.clear()
        return await callback.answer()

    await state.update_data(asgn_cafe_id=cafe_id)
    await state.set_state(AssignAdmin.pick_admin)

    buttons = [
        [InlineKeyboardButton(
            text=f"👤 {a.name} ({a.phone or 'tel yo`q'})",
            callback_data=f"asgn_admin:{cafe_id}:{a.telegram_id}"
        )]
        for a in available
    ]
    await callback.message.edit_text(
        f"☕ <b>{cafe.name}</b>{cur_text}\n\nBiriktirilmagan adminlar:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asgn_admin:"))
async def assign_admin_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    _, cafe_id, tg_id = callback.data.split(":")
    cafe_id, tg_id = int(cafe_id), int(tg_id)

    admin = await get_user_by_telegram_id(session, tg_id)
    cafe = await get_cafe_by_id(session, cafe_id)
    ok, msg = await add_cafe_admin(session, cafe_id, admin.id)

    if ok:
        # Cafe adminlari ro'yxatini yangilash
        current = await get_cafe_admins(session, cafe_id)
        names = ", ".join(a.name for a in current)
        await callback.message.edit_text(
            f"✅ <b>{admin.name}</b> → <b>{cafe.name}</b> cafesiga biriktirildi.\n\n"
            f"👥 Hozirgi adminlar ({len(current)}/{MAX_ADMINS_PER_CAFE}): {names}",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                admin.telegram_id,
                f"🎉 Siz <b>{cafe.name}</b> cafesiga admin qilib tayinlandingiz!\n"
                f"/start bosib admin panelni oching.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.message.edit_text(f"❌ {msg}")

    await state.clear()
    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


# ── Admin olish ───────────────────────────────────────────────────────────────

@router.message(F.text == "➖ Admin olish")
async def remove_start(message: Message, state: FSMContext, session: AsyncSession):
    if not is_owner(message):
        return
    cafes = await get_all_cafes(session)
    if not cafes:
        return await message.answer("❌ Hozircha cafe yo'q.")

    await state.set_state(RemoveAdmin.pick_cafe)
    await message.answer("☕ Qaysi cafeden admin olib tashlamoqchisiz?",
                         reply_markup=cafes_inline_kb(cafes, prefix="rm_cafe"))


@router.callback_query(F.data.startswith("rm_cafe:"))
async def remove_pick_cafe(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cafe_id = int(callback.data.split(":")[1])
    cafe = await get_cafe_by_id(session, cafe_id)
    admins = await get_cafe_admins(session, cafe_id)

    if not admins:
        await callback.message.edit_text(
            f"☕ <b>{cafe.name}</b>\n\n⚠️ Bu cafeda admin yo'q.", parse_mode="HTML"
        )
        await state.clear()
        return await callback.answer()

    await state.update_data(rm_cafe_id=cafe_id)
    await state.set_state(RemoveAdmin.pick_admin)

    buttons = [
        [InlineKeyboardButton(
            text=f"❌ {a.name} ({a.phone or 'tel yo`q'})",
            callback_data=f"rm_admin:{cafe_id}:{a.telegram_id}"
        )]
        for a in admins
    ]
    await callback.message.edit_text(
        f"☕ <b>{cafe.name}</b> — adminlar ({len(admins)}/{MAX_ADMINS_PER_CAFE}):\n\nKimni olib tashlamoqchisiz?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rm_admin:"))
async def remove_admin_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    _, cafe_id, tg_id = callback.data.split(":")
    cafe_id, tg_id = int(cafe_id), int(tg_id)

    admin = await get_user_by_telegram_id(session, tg_id)
    cafe = await get_cafe_by_id(session, cafe_id)
    await remove_cafe_admin(session, cafe_id, admin.id)

    remaining = await get_cafe_admins(session, cafe_id)
    remain_text = ", ".join(a.name for a in remaining) if remaining else "yo'q"

    await callback.message.edit_text(
        f"✅ <b>{admin.name}</b> — <b>{cafe.name}</b> cafesidan olib tashlandi.\n\n"
        f"👥 Qolgan adminlar: {remain_text}",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            admin.telegram_id,
            f"⚠️ Siz <b>{cafe.name}</b> cafesining admini emasligingiz tasdiqlandi.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.clear()
    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


# ── Cafe o'chirish ────────────────────────────────────────────────────────────

@router.message(F.text == "🗑 Cafe o'chirish")
async def cafe_delete_start(message: Message, session: AsyncSession):
    if not is_owner(message):
        return
    cafes = await get_all_cafes(session)
    if not cafes:
        return await message.answer("Hozircha cafe yo'q.")

    buttons = [[InlineKeyboardButton(text=f"🗑 {c.name}", callback_data=f"del_cafe:{c.id}")] for c in cafes]
    await message.answer(
        "⚠️ <b>Qaysi cafeni o'chirmoqchisiz?</b>\n\nCafe, menyusi va buyurtmalari o'chib ketadi!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("del_cafe:"))
async def cafe_delete_confirm(callback: CallbackQuery, session: AsyncSession):
    cafe_id = int(callback.data.split(":")[1])
    cafe = await get_cafe_by_id(session, cafe_id)
    if not cafe:
        return await callback.answer("Cafe topilmadi.", show_alert=True)
    await callback.message.edit_text(
        f"🗑 <b>{cafe.name}</b> cafesini o'chirishni tasdiqlaysizmi?\nBu amal qaytarib bo'lmaydi!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=f"del_cafe_ok:{cafe_id}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="del_cafe_cancel"),
        ]])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_cafe_ok:"))
async def cafe_delete_execute(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    cafe_id = int(callback.data.split(":")[1])
    cafe = await get_cafe_by_id(session, cafe_id)
    if not cafe:
        return await callback.answer("Cafe topilmadi.", show_alert=True)

    cafe_name = cafe.name
    admins = await get_cafe_admins(session, cafe_id)
    admin_tg_ids = [a.telegram_id for a in admins]

    await delete_cafe(session, cafe_id)

    await callback.message.edit_text(f"✅ <b>{cafe_name}</b> o'chirildi.", parse_mode="HTML")
    for tg_id in admin_tg_ids:
        try:
            await bot.send_message(tg_id, f"⚠️ <b>{cafe_name}</b> cafesi o'chirildi.", parse_mode="HTML")
        except Exception:
            pass

    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


@router.callback_query(F.data == "del_cafe_cancel")
async def cafe_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


# ── Cafeler ro'yxati ──────────────────────────────────────────────────────────

@router.message(F.text == "📊 Cafeler ro'yxati")
async def cafes_list(message: Message, session: AsyncSession):
    if not is_owner(message):
        return
    cafes = await get_all_cafes(session)
    if not cafes:
        return await message.answer("Hozircha cafe yo'q.")

    text = "📊 <b>Cafeler:</b>\n\n"
    for c in cafes:
        admins = await get_cafe_admins(session, c.id)
        loc = f"{c.latitude:.4f}, {c.longitude:.4f}" if c.latitude else "kiritilmagan"
        admin_text = ", ".join(f"{a.name} ({a.phone or 'tel yo`q'})" for a in admins) if admins else "—"
        text += (
            f"☕ <b>{c.name}</b>\n"
            f"   👥 Adminlar ({len(admins)}/{MAX_ADMINS_PER_CAFE}): {admin_text}\n"
            f"   📍 {loc}\n\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=owner_kb())


# ── Guruhlar ro'yxati ─────────────────────────────────────────────────────────

@router.message(F.text == "📋 Guruhlar ro'yxati")
async def channels_list(message: Message, session: AsyncSession):
    if not is_owner(message):
        return
    channels = await get_all_channels(session)
    if not channels:
        return await message.answer(
            "📋 Hozircha guruh/kanal yo'q.\n\n"
            "Botni guruh yoki kanalga admin qilib qo'ying — avtomatik qo'shiladi.",
            reply_markup=owner_kb()
        )

    type_icon = {"group": "👥", "supergroup": "👥", "channel": "📢"}
    text = "📋 <b>Guruh va kanallar:</b>\n\n"
    for ch in channels:
        icon = type_icon.get(ch.chat_type, "💬")
        text += f"{icon} <b>{ch.title}</b>\n   ID: <code>{ch.chat_id}</code>\n\n"

    # O'chirish tugmalari
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {ch.title}",
            callback_data=f"del_channel:{ch.id}"
        )]
        for ch in channels
    ]
    await message.answer(text, parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)


@router.callback_query(F.data.startswith("del_channel:"))
async def delete_channel(callback: CallbackQuery, session: AsyncSession):
    channel_id = int(callback.data.split(":")[1])
    ch = await get_channel_by_id(session, channel_id)
    if not ch:
        return await callback.answer("Topilmadi.", show_alert=True)
    title = ch.title
    await remove_channel(session, ch.chat_id)
    await callback.message.edit_text(
        f"🗑 <b>{title}</b> ro'yxatdan o'chirildi.", parse_mode="HTML"
    )
    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


# ── Xabar yuborish ────────────────────────────────────────────────────────────

@router.message(F.text == "📢 Guruh/Kanal xabari")
async def broadcast_start(message: Message, state: FSMContext, session: AsyncSession):
    if not is_owner(message):
        return
    channels = await get_all_channels(session)
    if not channels:
        return await message.answer(
            "❌ Hozircha guruh/kanal yo'q.\n"
            "Botni guruhga admin qilib qo'ying.",
            reply_markup=owner_kb()
        )

    await state.set_state(Broadcast.pick_targets)
    await state.update_data(selected_channels=[], all_channel_ids=[ch.id for ch in channels])

    type_icon = {"group": "👥", "supergroup": "👥", "channel": "📢"}
    buttons = []
    for ch in channels:
        icon = type_icon.get(ch.chat_type, "💬")
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {ch.title}",
            callback_data=f"bc_pick:{ch.id}"
        )])
    buttons.append([InlineKeyboardButton(text="✅ Barchasiga yuborish", callback_data="bc_all")])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel")])

    await message.answer(
        "📢 <b>Qaysi guruh/kanallarga xabar yubormoqchisiz?</b>\n\n"
        "Tanlang yoki barchasiga yuboring:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("bc_pick:"))
async def broadcast_pick_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    channel_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("selected_channels", [])

    if channel_id in selected:
        selected.remove(channel_id)
        await callback.answer("Olib tashlandi.")
    else:
        selected.append(channel_id)
        await callback.answer("Tanlandi! ✅")

    await state.update_data(selected_channels=selected)

    # Tugmalarni yangilash — tanlanganlarni belgilash
    channels = await get_all_channels(session)
    type_icon = {"group": "👥", "supergroup": "👥", "channel": "📢"}
    buttons = []
    for ch in channels:
        icon = type_icon.get(ch.chat_type, "💬")
        tick = "✅ " if ch.id in selected else ""
        buttons.append([InlineKeyboardButton(
            text=f"{tick}{icon} {ch.title}",
            callback_data=f"bc_pick:{ch.id}"
        )])
    buttons.append([InlineKeyboardButton(text="✅ Barchasiga yuborish", callback_data="bc_all")])
    if selected:
        buttons.append([InlineKeyboardButton(
            text=f"➡️ Davom etish ({len(selected)} ta tanlangan)",
            callback_data="bc_next"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel")])

    try:
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception:
        pass


@router.callback_query(F.data == "bc_all")
async def broadcast_all(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    channels = await get_all_channels(session)
    all_ids = [ch.id for ch in channels]
    await state.update_data(selected_channels=all_ids)
    await state.set_state(Broadcast.write_message)
    await callback.message.answer(
        f"✅ Barcha {len(all_ids)} ta guruh/kanal tanlandi.\n\n"
        "📝 Endi yubormoqchi bo'lgan xabarni yozing:\n"
        "(Matn, rasm, video, hujjat — barchasi qabul qilinadi)",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "bc_next")
async def broadcast_next(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    count = len(data.get("selected_channels", []))
    await state.set_state(Broadcast.write_message)
    await callback.message.answer(
        f"✅ {count} ta guruh/kanal tanlandi.\n\n"
        "📝 Endi yubormoqchi bo'lgan xabarni yozing:\n"
        "(Matn, rasm, video, hujjat — barchasi qabul qilinadi)",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "bc_cancel")
async def broadcast_cancel_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())


@router.message(Broadcast.write_message)
async def broadcast_write(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=owner_kb())

    # Xabarni saqlash — forward qilib yuboramiz
    await state.update_data(bc_msg_id=message.message_id, bc_from_chat=message.chat.id)
    await state.set_state(Broadcast.confirm)

    await message.answer(
        "👆 Yuqoridagi xabar yuboriladi.\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, yuborish", callback_data="bc_confirm"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"),
        ]])
    )


@router.callback_query(F.data == "bc_confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    selected_ids = data.get("selected_channels", [])
    msg_id = data["bc_msg_id"]
    from_chat = data["bc_from_chat"]
    await state.clear()

    channels = await get_all_channels(session)
    targets = [ch for ch in channels if ch.id in selected_ids]

    ok, fail = 0, 0
    failed_names = []
    for ch in targets:
        try:
            await bot.forward_message(
                chat_id=ch.chat_id,
                from_chat_id=from_chat,
                message_id=msg_id
            )
            ok += 1
        except Exception as e:
            fail += 1
            failed_names.append(ch.title)
            import logging
            logging.getLogger(__name__).error(f"Guruhga xabar yuborishda xato {ch.title}: {e}")

    result = f"📢 <b>Xabar yuborildi!</b>\n\n✅ Muvaffaqiyatli: {ok} ta"
    if fail:
        result += f"\n❌ Xatolik: {fail} ta\n" + "\n".join(f"  • {n}" for n in failed_names)

    await callback.message.edit_text(result, parse_mode="HTML")
    await callback.answer("Yuborildi!")
    await callback.message.answer("Boshqa amal:", reply_markup=owner_kb())