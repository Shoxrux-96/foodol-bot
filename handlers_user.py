from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from database import (
    get_or_create_user, get_user_by_telegram_id, set_user_phone,
    get_all_cafes, get_nearest_cafe, get_foods_by_cafe,
    get_food_by_id, get_cafe_by_id, get_order_by_id,
    create_order_with_items, get_order_items, get_orders_by_user,
    update_order_status
)
from models import Role, Order, User as UserModel, DeliveryType, OrderStatus
from keyboards import (
    phone_kb, location_kb, user_main_kb, admin_main_kb,
    cafes_inline_kb, food_carousel_kb, cart_kb,
    delivery_choice_kb, request_location_kb, order_manage_kb
)

router = Router()
logger = logging.getLogger(__name__)


# ── States ────────────────────────────────────────────────────────────────────

class UserReg(StatesGroup):
    phone = State()

class BrowseMenu(StatesGroup):
    viewing = State()
    enter_qty = State()

class NearestCafe(StatesGroup):
    location = State()

class PlaceOrder(StatesGroup):
    delivery_location = State()

class OwnerUserMode(StatesGroup):
    active = State()   # owner user rejimida


# ── Himoyalangan state kalitlari ─────────────────────────────────────────────
# Bu kalitlar state.clear() da o'chib ketmaydi

PROTECTED_KEYS = {"cart", "cafe_id", "food_ids", "current_index"}


async def safe_clear(state: FSMContext):
    """State ni tozalaydi, lekin savat va cafe ma'lumotlarini saqlaydi"""
    data = await state.get_data()
    saved = {k: v for k, v in data.items() if k in PROTECTED_KEYS}
    await state.clear()   # haqiqiy clear
    if saved:
        await state.update_data(**saved)


async def _reset_cart(state: FSMContext):
    """Faqat savatni tozalaydi"""
    data = await state.get_data()
    data.pop("cart", None)
    await state.set_data(data)

def get_cart(data: dict) -> dict:
    return data.get("cart", {})

def cart_total_items(cart: dict) -> int:
    return sum(cart.values())

async def build_cart_summary(cart: dict, session) -> tuple[str, float]:
    lines, total = [], 0.0
    for fid, qty in cart.items():
        food = await get_food_by_id(session, int(fid))
        if food:
            sub = food.price * qty
            total += sub
            qty_str = f"{qty:g}"
            lines.append(f"• {food.name} × {qty_str} — {sub:,.0f} so'm")
    lines.append(f"\n💰 Jami: {total:,.0f} so'm")
    return "\n".join(lines), total

async def _main_kb(state: FSMContext):
    current = await state.get_state()
    if current == OwnerUserMode.active:
        return owner_user_kb()
    return user_main_kb()


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(F.text == "/start")
async def user_start(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()  # /start da hamma narsa tozalanadi
    user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    if user.role == Role.owner:
        from handlers_owner import owner_kb
        return await message.answer(f"👑 Xush kelibsiz, {user.name}!", reply_markup=owner_kb())

    if user.role == Role.admin:
        return await message.answer(f"👨‍💼 Xush kelibsiz, {user.name}!", reply_markup=admin_main_kb())

    if not user.phone:
        await state.set_state(UserReg.phone)
        return await message.answer(
            f"👋 Salom, <b>{user.name}</b>!\n\nBotga xush kelibsiz 🍽\n"
            "Davom etish uchun telefon raqamingizni yuboring:",
            parse_mode="HTML", reply_markup=phone_kb()
        )

    await message.answer(
        f"🍽 <b>Asosiy menyu</b>\n\nNima qilmoqchisiz, {user.name}?",
        parse_mode="HTML", reply_markup=user_main_kb()
    )


# ── Owner → User rejimi ───────────────────────────────────────────────────────

def owner_user_kb():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Eng yaqin cafe"), KeyboardButton(text="📋 Barcha cafeler")],
            [KeyboardButton(text="🛒 Buyurtmalarim")],
            [KeyboardButton(text="🔙 Owner paneliga qaytish")],
        ],
        resize_keyboard=True
    )


@router.message(F.text == "👤 User rejimi")
async def enter_user_mode(message: Message, state: FSMContext, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user or user.role != Role.owner:
        return

    await safe_clear(state)
    await state.set_state(OwnerUserMode.active)
    await message.answer(
        "👤 <b>User rejimi</b>\n\n"
        "Endi oddiy foydalanuvchi kabi cafelerni ko'rib, buyurtma bera olasiz.\n\n"
        "Owner paneliga qaytish uchun '🔙 Owner paneliga qaytish' tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=owner_user_kb()
    )


@router.message(F.text == "🔙 Owner paneliga qaytish")
async def exit_user_mode(message: Message, state: FSMContext, session: AsyncSession):
    await safe_clear(state)
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.role == Role.owner:
        from handlers_owner import owner_kb
        await message.answer("👑 Owner panelga qaytdingiz.", reply_markup=owner_kb())
    else:
        await message.answer("Asosiy menyu:", reply_markup=user_main_kb())


# ── Ro'yxatdan o'tish ─────────────────────────────────────────────────────────

@router.message(UserReg.phone, F.contact)
async def save_phone(message: Message, state: FSMContext, session: AsyncSession):
    # Contact'dan telefon raqamni olish
    phone = message.contact.phone_number
    # Raqam + bilan boshlanmasa qo'shamiz
    if not phone.startswith("+"):
        phone = "+" + phone
    # DBga saqlash
    await set_user_phone(session, message.from_user.id, phone)
    await safe_clear(state)
    user = await get_user_by_telegram_id(session, message.from_user.id)
    await message.answer(
        f"✅ <b>Ro'yxatdan o'tdingiz!</b>\n\n"
        f"👤 Ism: {user.name}\n"
        f"📞 Tel: {phone}\n\n"
        f"Endi buyurtma berishingiz mumkin 👇",
        parse_mode="HTML",
        reply_markup=user_main_kb()
    )

@router.message(UserReg.phone)
async def save_phone_wrong(message: Message):
    await message.answer("❌ Iltimos, tugmani bosib telefon raqamini yuboring:", reply_markup=phone_kb())


# ── Eng yaqin cafe ────────────────────────────────────────────────────────────

@router.message(F.text == "📍 Eng yaqin cafe")
async def nearest_cafe_start(message: Message, state: FSMContext):
    await state.set_state(NearestCafe.location)
    await message.answer("📍 Lokatsiyangizni yuboring:", reply_markup=location_kb())

@router.message(NearestCafe.location, F.location)
async def find_nearest(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    cafe = await get_nearest_cafe(session, message.location.latitude, message.location.longitude)
    await safe_clear(state)
    if not cafe:
        return await message.answer("😔 Yaqin atrofda cafe topilmadi.", reply_markup=user_main_kb())

    foods = await get_foods_by_cafe(session, cafe.id)
    await message.answer(
        f"📍 Eng yaqin cafe:\n\n☕ <b>{cafe.name}</b>\n🍽 Menyu: {len(foods)} ta taom",
        parse_mode="HTML", reply_markup=user_main_kb()
    )
    if cafe.latitude:
        await bot.send_location(message.chat.id, cafe.latitude, cafe.longitude)
    if foods:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer(
            "Menyuni ko'rib buyurtma berasizmi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📋 Menyuni ko'rish", callback_data=f"cafe:{cafe.id}")
            ]])
        )


# ── Barcha cafeler ────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Barcha cafeler")
async def all_cafes(message: Message, session: AsyncSession):
    cafes = await get_all_cafes(session)
    if not cafes:
        return await message.answer("😔 Hozircha hech qanday cafe yo'q.", reply_markup=user_main_kb())
    await message.answer(
        "☕ <b>Cafeler ro'yxati</b>\n\nQaysi cafeni tanlaysiz?",
        parse_mode="HTML", reply_markup=cafes_inline_kb(cafes)
    )


# ── Cafe tanlash → carousel ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cafe:"))
async def cafe_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cafe_id = int(callback.data.split(":")[1])
    cafe = await get_cafe_by_id(session, cafe_id)
    foods = await get_foods_by_cafe(session, cafe_id)

    if not foods:
        await callback.message.answer(
            f"☕ <b>{cafe.name}</b>\n\n😔 Menyu hali to'ldirilmagan.", parse_mode="HTML"
        )
        return await callback.answer()

    await state.set_state(BrowseMenu.viewing)
    await state.update_data(
        cafe_id=cafe_id,
        food_ids=[f.id for f in foods],
        current_index=0,
        cart={}
    )
    await callback.answer()
    await _show_food_card(callback.message, state, session, index=0)


# ── Carousel ko'rsatish ───────────────────────────────────────────────────────

async def _show_food_card(message: Message, state: FSMContext, session: AsyncSession, index: int):
    data = await state.get_data()
    food_ids = data["food_ids"]
    cart = get_cart(data)

    food = await get_food_by_id(session, food_ids[index])
    total = len(food_ids)
    in_cart = cart.get(str(food.id), 0)

    caption = (
        f"🍽 <b>{food.name}</b>\n"
        f"💰 Narxi: {food.price:,.0f} so'm"
    )
    if in_cart:
        caption += f"\n🛒 Savatda: {in_cart} ta"

    cart_count = cart_total_items(cart)
    if cart_count:
        caption += f"\n\n📦 Savatingizda jami {cart_count} ta ovqat bor"

    kb = food_carousel_kb(food.id, index, total, in_cart)

    # Eski xabarni o'chirib yangi yuborish — rasm to'g'ri almashinsin
    try:
        await message.delete()
    except Exception:
        pass

    if food.photo:
        await message.answer_photo(food.photo, caption=caption, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(caption, parse_mode="HTML", reply_markup=kb)

    await state.update_data(current_index=index)


# ── Navigatsiya ◀️ ▶️ ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fnav:"))
async def food_nav(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    index = int(callback.data.split(":")[1])
    await callback.answer()
    await _show_food_card(callback.message, state, session, index=index)

@router.callback_query(F.data == "fnav_info")
async def nav_info(callback: CallbackQuery):
    await callback.answer()


# ── Buyurtma berish tugmasi bosildi → miqdor so'rash ─────────────────────────

@router.callback_query(F.data.startswith("forder:"))
async def ask_qty(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, food_id, index, total = callback.data.split(":")
    food_id, index = int(food_id), int(index)

    food = await get_food_by_id(session, food_id)
    await state.set_state(BrowseMenu.enter_qty)
    await state.update_data(order_food_id=food_id, order_food_index=index)

    data = await state.get_data()
    cart = get_cart(data)
    current_qty = cart.get(str(food_id), 0)

    hint = f" (hozir savatda: {current_qty} ta)" if current_qty else ""
    await callback.message.answer(
        f"🍽 <b>{food.name}</b> — {food.price:,.0f} so'm\n\n"
        f"Nechtasini buyurtma qilmoqchisiz{hint}?\n"
        f"Raqam yuboring (masalan: <b>2</b>):",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(BrowseMenu.enter_qty)
async def receive_qty(message: Message, state: FSMContext, session: AsyncSession):
    from keyboards import cancel_kb
    if message.text == "❌ Bekor qilish":
        await state.set_state(BrowseMenu.viewing)
        data = await state.get_data()
        index = data.get("current_index", 0)
        return await _show_food_card(message, state, session, index=index)

    # Kasr son qabul qilinadi: 2, 2.5, 0.5 kabi
    try:
        qty = float(message.text.strip().replace(",", "."))
        if qty <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ To'g'ri miqdor kiriting (masalan: 1, 2.5, 0.5):")

    data = await state.get_data()
    food_id = data["order_food_id"]
    index = data.get("order_food_index", 0)

    cart = get_cart(data)
    cart[str(food_id)] = qty
    await state.update_data(cart=cart, current_index=index)
    await state.set_state(BrowseMenu.viewing)

    food = await get_food_by_id(session, food_id)
    qty_str = f"{qty:g}"  # 2.0 → "2", 2.5 → "2.5"
    await message.answer(
        f"✅ <b>{food.name}</b> × {qty_str} savatga qo'shildi!",
        parse_mode="HTML",
        reply_markup=await _main_kb(state)
    )
    await _show_food_card(message, state, session, index=index)


# ── Savatni ko'rish ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "cart:view")
async def view_cart(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    cart = get_cart(data)
    if not cart:
        return await callback.answer("Savat bo'sh!", show_alert=True)

    summary, _ = await build_cart_summary(cart, session)
    await callback.message.answer(
        "🧾 <b>Sizning savatningiz:</b>\n\n" + summary,
        parse_mode="HTML", reply_markup=cart_kb(has_items=True)
    )
    await callback.answer()


# ── Savatni tozalash ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "cart:clear")
async def clear_cart(callback: CallbackQuery, state: FSMContext):
    await _reset_cart(state)
    try:
        await callback.message.edit_text("🗑 Savat tozalandi.")
    except Exception:
        await callback.message.answer("🗑 Savat tozalandi.")
    await callback.answer("Savat tozalandi!")


# ── Menyuga qaytish ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "cart:back")
async def back_to_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    index = data.get("current_index", 0)
    await state.set_state(BrowseMenu.viewing)
    await callback.answer()
    await _show_food_card(callback.message, state, session, index=index)


# ── Buyurtma berish — yetkazish usulini tanlash ───────────────────────────────

@router.callback_query(F.data == "cart:order")
async def choose_delivery(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    cart = get_cart(data)
    if not cart:
        return await callback.answer("Savat bo'sh!", show_alert=True)

    summary, total = await build_cart_summary(cart, session)
    await callback.message.answer(
        f"🧾 <b>Buyurtmangiz:</b>\n\n{summary}\n\nQanday olmoqchisiz?",
        parse_mode="HTML", reply_markup=delivery_choice_kb()
    )
    await callback.answer()


# ── Pickup ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "delivery:pickup")
async def handle_pickup(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    await callback.answer()
    await _finalize_order(callback.message, state, session, bot,
                          callback.from_user.id, DeliveryType.pickup)


# ── Delivery — lokatsiya so'rash ──────────────────────────────────────────────

@router.callback_query(F.data == "delivery:delivery")
async def handle_delivery_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlaceOrder.delivery_location)
    await callback.message.answer(
        "📍 <b>Yetkazib berish manzilingizni yuboring:</b>\n\n"
        "Pastdagi tugmani bosib lokatsiyangizni yuboring yoki xaritadan tanlang.",
        parse_mode="HTML",
        reply_markup=request_location_kb()
    )
    await callback.answer()


@router.message(PlaceOrder.delivery_location, F.location)
async def handle_delivery_location(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    dlat = message.location.latitude
    dlon = message.location.longitude
    # State ni saqlab qolamiz — faqat koordinatalarni qo'shamiz
    await state.update_data(dlat=dlat, dlon=dlon)
    # Buyurtmani yaratish
    await _finalize_order(
        message, state, session, bot,
        message.from_user.id, DeliveryType.delivery,
        dlat, dlon
    )


@router.message(PlaceOrder.delivery_location)
async def handle_delivery_location_wrong(message: Message):
    """Lokatsiya o'rniga matn yozilsa"""
    await message.answer(
        "❌ Iltimos, lokatsiya yuboring.\nPastdagi '📍 Lokatsiyamni yuborish' tugmasini bosing.",
        reply_markup=request_location_kb()
    )


# ── Buyurtmani yaratish ───────────────────────────────────────────────────────

async def _finalize_order(
    target, state: FSMContext, session, bot: Bot,
    from_user_id: int,
    delivery_type: DeliveryType,
    delivery_lat: float = None,
    delivery_lon: float = None
):
    data = await state.get_data()
    cart = get_cart(data)
    cafe_id = data.get("cafe_id")

    # Tekshiruvlar
    if not cart:
        return await target.answer("❌ Savat bo'sh. Avval ovqat tanlang.", reply_markup=user_main_kb())
    if not cafe_id:
        return await target.answer("❌ Cafe tanlanmagan. Qaytadan cafe tanlang.", reply_markup=user_main_kb())

    # User ni DB dan olish yoki yaratish
    user = await get_user_by_telegram_id(session, from_user_id)
    if not user:
        # Birinchi marta (masalan owner user rejimida)
        from database import get_or_create_user
        tg_user_name = getattr(target, "chat", None)
        name = getattr(tg_user_name, "full_name", None) or "Foydalanuvchi"
        user = await get_or_create_user(session, from_user_id, name)

    cafe = await get_cafe_by_id(session, cafe_id)
    if not cafe:
        return await target.answer("❌ Cafe topilmadi.", reply_markup=user_main_kb())

    items = [{"food_id": int(fid), "quantity": qty} for fid, qty in cart.items()]
    if not items:
        return await target.answer("❌ Savat bo'sh.", reply_markup=user_main_kb())

    order = await create_order_with_items(
        session, user.id, cafe_id, items,
        delivery_type=delivery_type,
        delivery_lat=delivery_lat, delivery_lon=delivery_lon
    )

    foods_map = {}
    for item in items:
        food = await get_food_by_id(session, item["food_id"])
        if food:
            foods_map[food.id] = food

    total_sum = sum(
        foods_map[i["food_id"]].price * i["quantity"]
        for i in items if i["food_id"] in foods_map
    )
    order_lines = "\n".join(
        f"• {foods_map[i['food_id']].name} × {i['quantity']} ta — {foods_map[i['food_id']].price * i['quantity']:,.0f} so'm"
        for i in items if i["food_id"] in foods_map
    )
    dlabel = "🏪 Cafedan olish" if delivery_type == DeliveryType.pickup else "🚗 Yetkazib berish"

    await target.answer(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"📋 Buyurtma #{order.id}\n"
        f"☕ {cafe.name} | {dlabel}\n\n"
        f"{order_lines}\n\n"
        f"💰 Jami: {total_sum:,.0f} so'm\n\n"
        f"⏳ Admin tasdiqlashini kuting...",
        parse_mode="HTML", reply_markup=await _main_kb(state)
    )

    if delivery_type == DeliveryType.pickup and cafe.latitude:
        await bot.send_location(target.chat.id, cafe.latitude, cafe.longitude)

    await _reset_cart(state)
    await _notify_admin(bot, session, order, user, cafe, items, foods_map,
                        total_sum, delivery_type, delivery_lat, delivery_lon, target.chat.id)


# ── Adminga xabar ─────────────────────────────────────────────────────────────

async def _notify_admin(bot, session, order, user, cafe, items, foods_map,
                        total_sum, delivery_type, delivery_lat, delivery_lon, chat_id):
    from database import get_cafe_admins
    admins = await get_cafe_admins(session, cafe.id)
    if not admins:
        logger.warning(f"Buyurtma #{order.id} uchun admin topilmadi (cafe: {cafe.name})")
        return

    is_delivery = delivery_type == DeliveryType.delivery
    dlabel = "🚗 Yetkazib berish" if is_delivery else "🏪 Cafedan olish"
    user_phone = user.phone or "❗ Telefon raqam yo'q"

    # Ovqatlar ro'yxati
    food_lines = "\n".join(
        f"  • {foods_map[i['food_id']].name} × {i['quantity']} ta"
        f" — {foods_map[i['food_id']].price * i['quantity']:,.0f} so'm"
        for i in items if i["food_id"] in foods_map
    )

    text = (
        f"🔔 <b>YANGI BUYURTMA #{order.id}</b>\n"
        f"{'─' * 25}\n"
        f"👤 <b>Mijoz:</b> {user.name}\n"
        f"📞 <b>Telefon:</b> {user_phone}\n"
        f"{'─' * 25}\n"
        f"☕ <b>Cafe:</b> {cafe.name}\n"
        f"🚩 <b>Turi:</b> {dlabel}\n"
        f"{'─' * 25}\n"
        f"{food_lines}\n"
        f"{'─' * 25}\n"
        f"💰 <b>Jami: {total_sum:,.0f} so'm</b>"
    )

    # Miqdor o'zgartirish tugmalari
    from database import get_order_items as _get_items
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    order_items = await _get_items(session, order.id)
    base_kb = order_manage_kb(order.id, is_delivery)
    edit_buttons = []
    for oi in order_items:
        food = foods_map.get(oi.food_id)
        if food:
            qty_str = f"{oi.quantity:g}"
            edit_buttons.append([InlineKeyboardButton(
                text=f"✏️ {food.name} ({qty_str}) — miqdor o'zgartirish",
                callback_data=f"editqty:{order.id}:{oi.id}:{food.id}"
            )])
    full_kb = InlineKeyboardMarkup(inline_keyboard=base_kb.inline_keyboard + edit_buttons)

    for admin in admins:
        try:
            await bot.send_message(
                admin.telegram_id, text,
                parse_mode="HTML",
                reply_markup=full_kb
            )
            if is_delivery and delivery_lat and delivery_lon:
                await bot.send_message(
                    admin.telegram_id,
                    f"📍 <b>Mijozning manzili</b> ({user.name}):",
                    parse_mode="HTML"
                )
                await bot.send_location(admin.telegram_id, delivery_lat, delivery_lon)
            logger.info(f"Buyurtma #{order.id} admin {admin.telegram_id} ga yuborildi")
        except Exception as e:
            logger.error(f"Admin {admin.telegram_id} ga xabar yuborishda xato: {e}")


# ── User vaqtni tasdiqlash/bekor qilish ──────────────────────────────────────

@router.callback_query(F.data.startswith("uconfirm:"))
async def user_confirm_time(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    _, action, order_id = callback.data.split(":")
    order_id = int(order_id)

    order = await get_order_by_id(session, order_id)
    if not order:
        return await callback.answer("Buyurtma topilmadi.", show_alert=True)

    from database import get_cafe_admins
    from database import get_cafe_by_id as _get_cafe
    cafe = await _get_cafe(session, order.cafe_id)
    admins = await get_cafe_admins(session, order.cafe_id)

    if action == "ok":
        # User tasdiqladi — adminga xabar
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Siz tasdiqlash bildirdingiz!</b>\nTayyorlanmoqda...",
            parse_mode="HTML"
        )
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_id,
                    f"✅ <b>Buyurtma #{order_id}</b>\n\n"
                    f"Mijoz vaqtni tasdiqladi — tayyorlay boshlang!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    elif action == "cancel":
        # User bekor qildi
        await update_order_status(session, order_id, OrderStatus.rejected)
        await callback.message.edit_text(
            f"❌ <b>Buyurtma #{order_id} bekor qilindi.</b>\n\nVaqt ko'p bo'lgani uchun bekor qildingiz.",
            parse_mode="HTML"
        )
        # Adminga xabar
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_id,
                    f"❌ <b>Buyurtma #{order_id}</b>\n\n"
                    f"Mijoz vaqt ko'p bo'lgani uchun buyurtmani bekor qildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()


# ── Miqdor o'zgarishini tasdiqlash/bekor qilish ──────────────────────────────

@router.callback_query(F.data.startswith("qtyconfirm:"))
async def qty_change_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    _, action, order_id = callback.data.split(":")
    order_id = int(order_id)

    order = await get_order_by_id(session, order_id)
    if not order:
        return await callback.answer("Buyurtma topilmadi.", show_alert=True)

    from database import get_cafe_admins
    admins = await get_cafe_admins(session, order.cafe_id)
    cafe = await get_cafe_by_id(session, order.cafe_id)

    if action == "ok":
        # User rozilashdi
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Siz o'zgarishni tasdiqladingiz!</b>",
            parse_mode="HTML"
        )
        # Adminga xabar
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_id,
                    f"✅ <b>Buyurtma #{order_id}</b>\n\n"
                    f"Mijoz yangi miqdorga rozi bo'ldi — buyurtma davom etmoqda.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    elif action == "cancel":
        # User bekor qildi
        await update_order_status(session, order_id, OrderStatus.rejected)
        await callback.message.edit_text(
            f"❌ <b>Buyurtma #{order_id} bekor qilindi.</b>\n\n"
            f"Miqdor o'zgarishi sizga mos kelmadi.",
            parse_mode="HTML"
        )
        # Adminga xabar
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_id,
                    f"❌ <b>Buyurtma #{order_id}</b>\n\n"
                    f"Mijoz yangi miqdorga rozi bo'lmadi — buyurtma bekor qilindi.\n"
                    f"Cafe: {cafe.name if cafe else '?'}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()

@router.message(F.text == "🛒 Buyurtmalarim")
async def my_orders(message: Message, state: FSMContext, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        return

    orders = await get_orders_by_user(session, user.id, limit=10)
    if not orders:
        return await message.answer("🛒 Hozircha buyurtma bermadingiz.", reply_markup=await _main_kb(state))

    status_map = {
        "new":        ("⏳", "Kutilmoqda"),
        "accepted":   ("✅", "Qabul qilindi"),
        "rejected":   ("❌", "Bekor qilindi"),
        "ready":      ("🍽", "Tayyor!"),
        "delivering": ("🚗", "Yetkazilmoqda"),
        "delivered":  ("📦", "Yetkazildi"),
    }
    d_icon = {"pickup": "🏪", "delivery": "🚗"}

    text = "🛒 <b>Buyurtmalarim</b>\n\n"
    for o in orders:
        emoji, label = status_map.get(o.status.value, ("❓", o.status.value))
        icon = d_icon.get(o.delivery_type.value, "")
        cafe = await get_cafe_by_id(session, o.cafe_id)
        items = await get_order_items(session, o.id)

        lines, total = [], 0.0
        for item in items:
            food = await get_food_by_id(session, item.food_id)
            if food:
                sub = food.price * item.quantity
                total += sub
                lines.append(f"   • {food.name} × {item.quantity} ta")

        text += (
            f"{emoji} <b>#{o.id}</b> {icon} {cafe.name if cafe else '?'} — {label}\n"
            + "\n".join(lines)
            + f"\n   💰 {total:,.0f} so'm\n\n"
        )

    await message.answer(text, parse_mode="HTML", reply_markup=await _main_kb(state))


# ── cancel_kb import ──────────────────────────────────────────────────────────

def cancel_kb():
    from keyboards import cancel_kb as _ckb
    return _ckb()