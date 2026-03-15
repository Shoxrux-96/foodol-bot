from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    get_user_by_telegram_id, get_cafes_by_admin,
    create_food, get_foods_by_cafe, get_food_by_id,
    update_food, delete_food,
    get_orders_by_cafe, update_order_status,
    get_order_by_id, get_cafe_by_id, get_order_items,
    get_order_item_by_id, update_order_item_quantity
)
from models import Role, OrderStatus, DeliveryType
from keyboards import (
    admin_main_kb, cancel_kb, cafes_inline_kb,
    menu_manage_kb, food_manage_kb, food_edit_kb,
    order_manage_kb, order_accepted_kb
)

router = Router()


# ── States ────────────────────────────────────────────────────────────────────

class FoodAdd(StatesGroup):
    photo = State()
    name = State()
    price = State()

class FoodEdit(StatesGroup):
    waiting = State()

class OrderTime(StatesGroup):
    waiting = State()

class EditQty(StatesGroup):
    waiting = State()


# ── Helper ────────────────────────────────────────────────────────────────────

async def get_admin_cafes(session, telegram_id):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user or user.role not in (Role.admin, Role.owner):
        return None, []
    cafes = await get_cafes_by_admin(session, user.id)
    return user, cafes


async def pick_or_act(message_or_cb, session, telegram_id, prefix, action_text, callback=False):
    """
    Agar admin 1 ta cafega biriktirilgan bo'lsa — to'g'ridan-to'g'ri davom etadi (cafe_id qaytaradi).
    Ko'p cafe bo'lsa — tanlash klaviaturasi ko'rsatiladi (None qaytaradi).
    """
    _, cafes = await get_admin_cafes(session, telegram_id)
    if not cafes:
        if callback:
            await message_or_cb.answer("❌ Sizga cafe biriktirilmagan.", show_alert=True)
        else:
            await message_or_cb.answer("❌ Sizga cafe biriktirilmagan.\nOwner sizni cafega biriktirishi kerak.")
        return None

    if len(cafes) == 1:
        return cafes[0]

    # Ko'p cafe — tanlash
    kb = cafes_inline_kb(cafes, prefix=prefix)
    if callback:
        await message_or_cb.message.answer(f"☕ {action_text}:", reply_markup=kb)
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(f"☕ {action_text}:", reply_markup=kb)
    return None


# ── Cafe ma'lumoti ────────────────────────────────────────────────────────────

@router.message(F.text == "ℹ️ Cafem ma'lumoti")
async def cafe_info(message: Message, session: AsyncSession):
    cafe = await pick_or_act(message, session, message.from_user.id,
                              "adm_info", "Qaysi cafening ma'lumotini ko'rmoqchisiz")
    if cafe:
        await _show_cafe_info(message, session, cafe)


@router.callback_query(F.data.startswith("adm_info:"))
async def cafe_info_cb(callback: CallbackQuery, session: AsyncSession):
    cafe = await get_cafe_by_id(session, int(callback.data.split(":")[1]))
    await callback.answer()
    await _show_cafe_info(callback.message, session, cafe)


async def _show_cafe_info(target, session, cafe):
    foods = await get_foods_by_cafe(session, cafe.id)
    orders = await get_orders_by_cafe(session, cafe.id, OrderStatus.new)
    loc = f"{cafe.latitude:.4f}, {cafe.longitude:.4f}" if cafe.latitude else "kiritilmagan"
    await target.answer(
        f"☕ <b>{cafe.name}</b>\n\n"
        f"📍 Lokatsiya: {loc}\n"
        f"🍽 Menyu: {len(foods)} ta ovqat\n"
        f"📦 Yangi buyurtmalar: {len(orders)} ta",
        parse_mode="HTML"
    )


# ── Menyu boshqaruv ───────────────────────────────────────────────────────────

@router.message(F.text == "📋 Menyu boshqaruv")
async def menu_manage(message: Message, state: FSMContext, session: AsyncSession):
    cafe = await pick_or_act(message, session, message.from_user.id,
                              "adm_menu", "Qaysi cafening menyusini boshqarmoqchisiz")
    if cafe:
        await state.update_data(admin_cafe_id=cafe.id)
        await message.answer(f"📋 <b>{cafe.name}</b> — menyu:", parse_mode="HTML", reply_markup=menu_manage_kb())


@router.callback_query(F.data.startswith("adm_menu:"))
async def menu_manage_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cafe = await get_cafe_by_id(session, int(callback.data.split(":")[1]))
    await state.update_data(admin_cafe_id=cafe.id)
    await callback.message.answer(f"📋 <b>{cafe.name}</b> — menyu:", parse_mode="HTML", reply_markup=menu_manage_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:list")
async def menu_list(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    cafe_id = data.get("admin_cafe_id")
    if not cafe_id:
        _, cafes = await get_admin_cafes(session, callback.from_user.id)
        if not cafes:
            return await callback.answer("Cafe topilmadi.", show_alert=True)
        cafe_id = cafes[0].id

    foods = await get_foods_by_cafe(session, cafe_id)
    if not foods:
        await callback.message.edit_text("Menyu bo'sh. Ovqat qo'shing.", reply_markup=menu_manage_kb())
        return await callback.answer()

    cafe = await get_cafe_by_id(session, cafe_id)
    await callback.message.edit_text(f"📋 <b>{cafe.name}</b> menyusi:", parse_mode="HTML")
    await callback.answer()
    for f in foods:
        caption = f"🍽 <b>{f.name}</b>\n💰 {f.price:,.0f} so'm"
        if f.photo:
            await callback.message.answer_photo(f.photo, caption=caption, parse_mode="HTML", reply_markup=food_manage_kb(f.id))
        else:
            await callback.message.answer(caption, parse_mode="HTML", reply_markup=food_manage_kb(f.id))


# ── Ovqat qo'shish ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:add")
async def add_food_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    cafe_id = data.get("admin_cafe_id")
    if not cafe_id:
        _, cafes = await get_admin_cafes(session, callback.from_user.id)
        if not cafes:
            return await callback.answer("Cafe topilmadi.", show_alert=True)
        cafe_id = cafes[0].id

    await state.set_state(FoodAdd.photo)
    await state.update_data(cafe_id=cafe_id)
    await callback.message.answer("📷 Ovqat rasmini yuboring:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(FoodAdd.photo, F.photo)
async def add_food_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(FoodAdd.name)
    await message.answer("📝 Ovqat nomini kiriting:")


@router.message(FoodAdd.photo)
async def add_food_photo_wrong(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())
    await message.answer("❌ Iltimos rasm yuboring.")


@router.message(FoodAdd.name)
async def add_food_name(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())
    await state.update_data(food_name=message.text.strip())
    await state.set_state(FoodAdd.price)
    await message.answer("💰 Narxini kiriting (so'mda):")


@router.message(FoodAdd.price)
async def add_food_price(message: Message, state: FSMContext, session: AsyncSession):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())
    try:
        price = float(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        return await message.answer("❌ Faqat raqam kiriting:")

    data = await state.get_data()
    food = await create_food(session, data["cafe_id"], data["food_name"], price, data["photo"])
    await state.clear()
    await message.answer(
        f"✅ <b>{food.name}</b> — {food.price:,.0f} so'm menyuga qo'shildi!",
        parse_mode="HTML", reply_markup=admin_main_kb()
    )


# ── Ovqat o'chirish ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fdel:"))
async def food_delete(callback: CallbackQuery, session: AsyncSession):
    food_id = int(callback.data.split(":")[1])
    food = await get_food_by_id(session, food_id)
    if not food:
        return await callback.answer("Ovqat topilmadi.", show_alert=True)
    name = food.name
    await delete_food(session, food_id)
    await callback.message.delete()
    await callback.message.answer(f"🗑 <b>{name}</b> menyudan o'chirildi.", parse_mode="HTML")
    await callback.answer()


# ── Ovqat tahrirlash ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fedit:"))
async def food_edit_menu(callback: CallbackQuery, session: AsyncSession):
    food_id = int(callback.data.split(":")[1])
    food = await get_food_by_id(session, food_id)
    if not food:
        return await callback.answer("Ovqat topilmadi.", show_alert=True)
    await callback.message.answer(
        f"✏️ <b>{food.name}</b> — {food.price:,.0f} so'm\n\nNimani o'zgartirmoqchisiz?",
        parse_mode="HTML", reply_markup=food_edit_kb(food_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fedit_field:"))
async def food_edit_field(callback: CallbackQuery, state: FSMContext):
    _, food_id, field = callback.data.split(":")
    await state.set_state(FoodEdit.waiting)
    await state.update_data(edit_food_id=int(food_id), edit_field=field)
    prompts = {"photo": "📷 Yangi rasmni yuboring:", "name": "📝 Yangi nomini kiriting:", "price": "💰 Yangi narxini kiriting:"}
    await callback.message.answer(prompts[field], reply_markup=cancel_kb())
    await callback.answer()


@router.message(FoodEdit.waiting)
async def food_edit_apply(message: Message, state: FSMContext, session: AsyncSession):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())

    data = await state.get_data()
    food_id, field = data["edit_food_id"], data["edit_field"]

    if field == "photo":
        if not message.photo:
            return await message.answer("❌ Rasm yuboring:")
        await update_food(session, food_id, photo=message.photo[-1].file_id)
    elif field == "name":
        await update_food(session, food_id, name=message.text.strip())
    elif field == "price":
        try:
            price = float(message.text.replace(" ", "").replace(",", ""))
        except ValueError:
            return await message.answer("❌ Faqat raqam kiriting:")
        await update_food(session, food_id, price=price)

    await state.clear()
    food = await get_food_by_id(session, food_id)
    await message.answer(
        f"✅ <b>{food.name}</b> yangilandi! — {food.price:,.0f} so'm",
        parse_mode="HTML", reply_markup=admin_main_kb()
    )


# ── Buyurtmalar ───────────────────────────────────────────────────────────────

@router.message(F.text == "📦 Buyurtmalar")
async def show_orders(message: Message, session: AsyncSession):
    cafe = await pick_or_act(message, session, message.from_user.id,
                              "adm_orders", "Qaysi cafening buyurtmalarini ko'rmoqchisiz")
    if cafe:
        await _show_cafe_orders(message, session, cafe)


@router.callback_query(F.data.startswith("adm_orders:"))
async def orders_cafe_cb(callback: CallbackQuery, session: AsyncSession):
    cafe = await get_cafe_by_id(session, int(callback.data.split(":")[1]))
    await callback.answer()
    await _show_cafe_orders(callback.message, session, cafe)


async def _show_cafe_orders(target, session, cafe):
    orders = await get_orders_by_cafe(session, cafe.id, OrderStatus.new)
    if not orders:
        return await target.answer(f"📦 <b>{cafe.name}</b> — yangi buyurtma yo'q.", parse_mode="HTML")
    await target.answer(f"📦 <b>{cafe.name}</b> — yangi buyurtmalar: {len(orders)} ta", parse_mode="HTML")
    for order in orders:
        await _send_order_card(target, session, order, cafe)


async def _send_order_card(target, session, order, cafe=None):
    from models import User as UserModel
    buyer = await session.get(UserModel, order.user_id)
    if not cafe:
        cafe = await get_cafe_by_id(session, order.cafe_id)

    items = await get_order_items(session, order.id)
    lines, total = [], 0
    for item in items:
        food = await get_food_by_id(session, item.food_id)
        if food:
            sub = food.price * item.quantity
            total += sub
            qty_str = f"{item.quantity:g}"
            lines.append(f"🍽 {food.name} × {qty_str} — {sub:,.0f} so'm")

    is_delivery = order.delivery_type == DeliveryType.delivery
    dlabel = "🚗 Yetkazib berish" if is_delivery else "🏪 Cafedan olish"
    phone = buyer.phone or "ko'rsatilmagan"

    text = (
        f"🆕 <b>Buyurtma #{order.id}</b>\n\n"
        f"👤 Mijoz: {buyer.name}\n"
        f"📞 Tel: {phone}\n"
        f"{dlabel}\n\n"
        + "\n".join(lines)
        + f"\n\n💰 Jami: {total:,.0f} so'm"
    )

    # Asosiy tugmalar + miqdor o'zgartirish
    from keyboards import order_manage_kb
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    base_kb = order_manage_kb(order.id, is_delivery)
    # Har bir item uchun miqdor o'zgartirish tugmasini qo'shamiz
    edit_buttons = []
    for item in items:
        food = await get_food_by_id(session, item.food_id)
        if food:
            qty_str = f"{item.quantity:g}"
            edit_buttons.append([InlineKeyboardButton(
                text=f"✏️ {food.name} ({qty_str}) — miqdor o'zgartirish",
                callback_data=f"editqty:{order.id}:{item.id}:{food.id}"
            )])

    all_rows = base_kb.inline_keyboard + edit_buttons
    kb = InlineKeyboardMarkup(inline_keyboard=all_rows)
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


# ── Buyurtma holati ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("order:"))
async def handle_order_action(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    parts = callback.data.split(":")
    action, order_id = parts[1], int(parts[2])

    order = await get_order_by_id(session, order_id)
    if not order:
        return await callback.answer("Buyurtma topilmadi.", show_alert=True)

    from models import User as UserModel
    buyer = await session.get(UserModel, order.user_id)

    items = await get_order_items(session, order_id)
    item_names = []
    for item in items:
        food = await get_food_by_id(session, item.food_id)
        if food:
            item_names.append(f"{food.name} × {item.quantity} ta")
    items_text = ", ".join(item_names) if item_names else "ovqatlar"
    is_delivery = order.delivery_type == DeliveryType.delivery

    # ── Pishirish vaqtini belgilash ─────────────────────────────────────────
    if action == "time":
        await state.set_state(OrderTime.waiting)
        await state.update_data(
            order_id=order_id,
            buyer_tg_id=buyer.telegram_id,
            is_delivery=is_delivery,
            items_text=items_text
        )
        await callback.message.answer(
            f"⏰ <b>Buyurtma #{order_id}</b> uchun pishirish/tayyorlash vaqtini kiriting:\n"
            f"({items_text})\n\n"
            f"Masalan: <i>30 daqiqa</i>, <i>1 soat</i>, <i>14:30 da tayyor</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
        return await callback.answer()

    # ── Boshqa statuslar ────────────────────────────────────────────────────
    status_map = {
        "accept":     OrderStatus.accepted,
        "reject":     OrderStatus.rejected,
        "ready":      OrderStatus.ready,
        "delivering": OrderStatus.delivering,
        "delivered":  OrderStatus.delivered,
    }
    user_msgs = {
        "accept":     f"✅ Buyurtma #{order_id} qabul qilindi!\n🍽 {items_text} tayyorlanmoqda...",
        "reject":     f"❌ Buyurtma #{order_id} bekor qilindi.\nKerakli bo'lsa qayta buyurtma bering.",
        "ready":      f"🍽 Buyurtma #{order_id} tayyor!\n{items_text} olib ketishingiz mumkin.",
        "delivering": f"🚗 Buyurtma #{order_id} yo'lda!\n{items_text} yetkazilmoqda...",
        "delivered":  f"📦 Buyurtma #{order_id} yetkazildi!\nIshtaha bo'lsin! 😊",
    }
    admin_labels = {
        "accept":     "✅ Qabul qilindi",
        "reject":     "❌ Bekor qilindi",
        "ready":      "🍽 Tayyor",
        "delivering": "🚗 Yetkazilmoqda",
        "delivered":  "📦 Yetkazildi",
    }

    new_status = status_map.get(action)
    if not new_status:
        return await callback.answer("Noto'g'ri amal.")

    await update_order_status(session, order_id, new_status)

    # Userga xabar
    try:
        await bot.send_message(buyer.telegram_id, user_msgs[action], parse_mode="HTML")
    except Exception:
        pass

    # Admin xabarini yangilash — klaviatura holat bo'yicha
    if action == "accept":
        new_kb = order_accepted_kb(order_id, is_delivery)
    elif action in ("delivering",):
        # Yetkazilmoqda — faqat "Yetkazildi" qoladi
        new_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Yetkazildi", callback_data=f"order:delivered:{order_id}")
        ]])
    else:
        new_kb = None

    try:
        new_text = callback.message.text + f"\n\n<b>— {admin_labels[action]}</b>"
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_kb)
    except Exception:
        pass

    await callback.answer(admin_labels[action])


# ── Pishirish vaqtini belgilash ───────────────────────────────────────────────

@router.message(OrderTime.waiting)
async def set_order_time(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())

    data = await state.get_data()
    order_id = data["order_id"]
    buyer_tg_id = data["buyer_tg_id"]
    is_delivery = data.get("is_delivery", False)
    items_text = data.get("items_text", "buyurtma")
    time_text = message.text.strip()

    # Buyurtmani accepted ga o'tkazamiz
    await update_order_status(session, order_id, OrderStatus.accepted)
    await state.clear()

    # Userga vaqt yuboramiz — u tasdiqlashi kerak
    from keyboards import user_time_confirm_kb
    try:
        await bot.send_message(
            buyer_tg_id,
            f"⏰ <b>Buyurtma #{order_id}</b>\n\n"
            f"🍽 {items_text}\n\n"
            f"🕐 Taxminiy tayyorlanish vaqti: <b>{time_text}</b>\n\n"
            f"Shu vaqtni kutib tura olasizmi?",
            parse_mode="HTML",
            reply_markup=user_time_confirm_kb(order_id)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"User {buyer_tg_id} ga vaqt xabari yuborishda xato: {e}")

    # Adminga tasdiqlash xabari + to'liq tugmalar (yetkazildi saqlanadi)
    from keyboards import order_timed_kb
    await message.answer(
        f"✅ <b>Buyurtma #{order_id}</b> uchun vaqt yuborildi: <b>{time_text}</b>\n\n"
        f"User tasdiqlashi kutilmoqda...",
        parse_mode="HTML",
        reply_markup=order_timed_kb(order_id, is_delivery)
    )


# ── Buyurtma miqdorini o'zgartirish (admin) ───────────────────────────────────

@router.callback_query(F.data.startswith("editqty:"))
async def editqty_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, order_id, item_id, food_id = callback.data.split(":")
    order_id, item_id, food_id = int(order_id), int(item_id), int(food_id)

    food = await get_food_by_id(session, food_id)
    item = await get_order_item_by_id(session, item_id)
    if not food or not item:
        return await callback.answer("Mahsulot topilmadi.", show_alert=True)

    qty_str = f"{item.quantity:g}"
    await state.set_state(EditQty.waiting)
    await state.update_data(
        edit_order_id=order_id,
        edit_item_id=item_id,
        edit_food_id=food_id,
        edit_buyer_id=None  # keyinroq olamiz
    )

    # buyer_id ni order dan olamiz
    order = await get_order_by_id(session, order_id)
    await state.update_data(edit_buyer_tg=None, edit_order_id=order_id,
                            edit_item_id=item_id, edit_food_id=food_id,
                            edit_old_qty=item.quantity, edit_user_id=order.user_id)

    await callback.message.answer(
        f"✏️ <b>{food.name}</b>\n\n"
        f"Hozirgi miqdor: <b>{qty_str}</b>\n"
        f"Narxi: {food.price:,.0f} so'm / birlik\n\n"
        f"Yangi miqdorni kiriting (masalan: 2.5, 1, 0.5):",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(EditQty.waiting)
async def editqty_apply(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        return await message.answer("Bekor qilindi.", reply_markup=admin_main_kb())

    try:
        new_qty = float(message.text.strip().replace(",", "."))
        if new_qty <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ To'g'ri miqdor kiriting (masalan: 2.5):")

    data = await state.get_data()
    item_id = data["edit_item_id"]
    food_id = data["edit_food_id"]
    order_id = data["edit_order_id"]
    old_qty = data["edit_old_qty"]
    user_id = data["edit_user_id"]

    await update_order_item_quantity(session, item_id, new_qty)
    await state.clear()

    food = await get_food_by_id(session, food_id)
    old_sum = food.price * old_qty
    new_sum = food.price * new_qty
    old_str = f"{old_qty:g}"
    new_str = f"{new_qty:g}"

    await message.answer(
        f"✅ <b>Buyurtma #{order_id}</b> — miqdor yangilandi:\n\n"
        f"🍽 {food.name}\n"
        f"📊 {old_str} → {new_str}\n"
        f"💰 {old_sum:,.0f} → {new_sum:,.0f} so'm",
        parse_mode="HTML",
        reply_markup=admin_main_kb()
    )

    # Userga tugmali xabar yuborish
    from models import User as UserModel
    from keyboards import qty_change_confirm_kb
    buyer = await session.get(UserModel, user_id)
    if buyer:
        # Barcha items ni hisoblash — yangi jami narx
        from database import get_order_items
        all_items = await get_order_items(session, order_id)
        total_new = 0.0
        item_lines = []
        for oi in all_items:
            f = await get_food_by_id(session, oi.food_id)
            if f:
                sub = f.price * oi.quantity
                total_new += sub
                qty_s = f"{oi.quantity:g}"
                marker = " ← o'zgartirildi" if oi.id == item_id else ""
                item_lines.append(f"• {f.name} × {qty_s} — {sub:,.0f} so'm{marker}")

        try:
            await bot.send_message(
                buyer.telegram_id,
                f"⚠️ <b>Buyurtma #{order_id}</b> da o'zgarish bo'ldi:\n\n"
                f"🍽 {food.name}\n"
                f"📊 Miqdor: <b>{old_str} → {new_str}</b>\n"
                f"💰 {old_sum:,.0f} → <b>{new_sum:,.0f} so'm</b>\n\n"
                f"📋 Yangilangan buyurtma:\n"
                + "\n".join(item_lines) +
                f"\n\n💰 Jami: <b>{total_new:,.0f} so'm</b>\n\n"
                f"Davom etasizmi?",
                parse_mode="HTML",
                reply_markup=qty_change_confirm_kb(order_id)
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"User ga miqdor xabari yuborishda xato: {e}")