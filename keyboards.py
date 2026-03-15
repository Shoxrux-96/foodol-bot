from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


# ── Reply keyboards ───────────────────────────────────────────────────────────

def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )


def location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )


def user_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Eng yaqin cafe"), KeyboardButton(text="📋 Barcha cafeler")],
            [KeyboardButton(text="🛒 Buyurtmalarim")],
        ],
        resize_keyboard=True
    )


def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Menyu boshqaruv"), KeyboardButton(text="📦 Buyurtmalar")],
            [KeyboardButton(text="ℹ️ Cafem ma'lumoti")],
        ],
        resize_keyboard=True
    )


def owner_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Cafe qo'shish"), KeyboardButton(text="➕ Admin qo'shish")],
            [KeyboardButton(text="🔗 Admin biriktirish"), KeyboardButton(text="🗑 Cafe o'chirish")],
            [KeyboardButton(text="📊 Cafeler ro'yxati")],
        ],
        resize_keyboard=True
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )


# ── Inline: cafeler ───────────────────────────────────────────────────────────

def cafes_inline_kb(cafes: list, prefix: str = "cafe") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"☕ {c.name}", callback_data=f"{prefix}:{c.id}")]
        for c in cafes
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Inline: ovqat carousel ────────────────────────────────────────────────────

def food_carousel_kb(food_id: int, index: int, total: int, in_cart: int) -> InlineKeyboardMarkup:
    """
    Navigatsiya + savatga qo'shish (miqdor qo'lda yoziladi)
    """
    rows = []

    # Navigatsiya (agar 1 dan ko'p ovqat bo'lsa)
    if total > 1:
        prev_i = (index - 1) % total
        next_i = (index + 1) % total
        rows.append([
            InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"fnav:{prev_i}"),
            InlineKeyboardButton(text=f"{index + 1} / {total}", callback_data="fnav_info"),
            InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"fnav:{next_i}"),
        ])

    # Buyurtma berish tugmasi
    order_label = f"🛒 Buyurtma berish" if in_cart == 0 else f"🛒 Yangilash (hozir: {in_cart} ta)"
    rows.append([InlineKeyboardButton(text=order_label, callback_data=f"forder:{food_id}:{index}:{total}")])

    # Savat ko'rish
    if in_cart > 0:
        rows.append([InlineKeyboardButton(text="🧾 Savatni ko'rish", callback_data="cart:view")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_choice_kb() -> InlineKeyboardMarkup:
    """Savatni buyurtma berishdan oldin — olish usulini tanlash"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Cafedan olaman", callback_data="delivery:pickup")],
        [InlineKeyboardButton(text="🚗 Yetkazib berish", callback_data="delivery:delivery")],
    ])


def request_location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Lokatsiyamni yuborish", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )


def cart_kb(has_items: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if has_items:
        rows.append([InlineKeyboardButton(text="📤 Buyurtma berish", callback_data="cart:order")])
    rows.append([InlineKeyboardButton(text="🗑 Savatni tozalash", callback_data="cart:clear")])
    rows.append([InlineKeyboardButton(text="◀️ Menyuga qaytish", callback_data="cart:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



# ── Inline: menyu boshqaruv (admin) ──────────────────────────────────────────

def menu_manage_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ovqat qo'shish", callback_data="menu:add")],
        [InlineKeyboardButton(text="📋 Barcha ovqatlar", callback_data="menu:list")],
    ])


def food_manage_kb(food_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"fedit:{food_id}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"fdel:{food_id}"),
        ],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:list")],
    ])


def food_edit_kb(food_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Rasm", callback_data=f"fedit_field:{food_id}:photo")],
        [InlineKeyboardButton(text="📝 Nom", callback_data=f"fedit_field:{food_id}:name")],
        [InlineKeyboardButton(text="💰 Narx", callback_data=f"fedit_field:{food_id}:price")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"fedit:{food_id}")],
    ])


# ── Inline: buyurtma boshqaruv (admin) ───────────────────────────────────────

def order_manage_kb(order_id: int, is_delivery: bool = False) -> InlineKeyboardMarkup:
    """Yangi buyurtma kelganda admin ko'radigan tugmalar"""
    rows = [
        [
            InlineKeyboardButton(text="✅ Qabul", callback_data=f"order:accept:{order_id}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data=f"order:reject:{order_id}"),
        ],
        [InlineKeyboardButton(text="⏰ Pishirish vaqtini belgilash", callback_data=f"order:time:{order_id}")],
    ]
    if is_delivery:
        rows.append([InlineKeyboardButton(text="🚗 Yetkazilmoqda", callback_data=f"order:delivering:{order_id}")])
        rows.append([InlineKeyboardButton(text="📦 Yetkazildi", callback_data=f"order:delivered:{order_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🍽 Tayyor — olib ketsa bo'ladi", callback_data=f"order:ready:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_timed_kb(order_id: int, is_delivery: bool = False) -> InlineKeyboardMarkup:
    """Vaqt belgilangandan keyin — yetkazildi tugmasi saqlanadi"""
    rows = [
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order:reject:{order_id}")],
    ]
    if is_delivery:
        rows.append([InlineKeyboardButton(text="🚗 Yetkazilmoqda", callback_data=f"order:delivering:{order_id}")])
        rows.append([InlineKeyboardButton(text="📦 Yetkazildi", callback_data=f"order:delivered:{order_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🍽 Tayyor — olib ketsa bo'ladi", callback_data=f"order:ready:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_accepted_kb(order_id: int, is_delivery: bool = False) -> InlineKeyboardMarkup:
    """Qabul qilingandan keyin"""
    rows = [
        [InlineKeyboardButton(text="⏰ Pishirish vaqtini belgilash", callback_data=f"order:time:{order_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order:reject:{order_id}")],
    ]
    if is_delivery:
        rows.append([InlineKeyboardButton(text="🚗 Yetkazilmoqda", callback_data=f"order:delivering:{order_id}")])
        rows.append([InlineKeyboardButton(text="📦 Yetkazildi", callback_data=f"order:delivered:{order_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🍽 Tayyor — olib ketsa bo'ladi", callback_data=f"order:ready:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qty_change_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    """Miqdor o'zgartirilganda userga — rozi bo'lish yoki bekor qilish"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Roziman, davom etsin", callback_data=f"qtyconfirm:ok:{order_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilaman", callback_data=f"qtyconfirm:cancel:{order_id}")],
    ])
    """User vaqtni ko'rib — kutaman yoki bekor qilaman"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, kutaman", callback_data=f"uconfirm:ok:{order_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilaman", callback_data=f"uconfirm:cancel:{order_id}")],
    ])


# ── Inline: owner ─────────────────────────────────────────────────────────────

def admins_inline_kb(admins: list, cafe_id: int, skip: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    for a in admins:
        phone = a.phone or "tel yo'q"
        buttons.append([InlineKeyboardButton(
            text=f"👤 {a.name} ({phone})",
            callback_data=f"setadmin:{cafe_id}:{a.telegram_id}"
        )])
    if skip:
        buttons.append([InlineKeyboardButton(text="⏭ Keyinroq biriktiraman", callback_data="setadmin_skip")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)